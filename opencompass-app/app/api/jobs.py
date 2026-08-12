"""任务创建 + 查询。"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.core.dataset_registry import DatasetRegistry
from app.core.dataset_whitelist import DatasetWhitelist
from app.core.job_state_machine import can_delete, can_stop
from app.core.model_whitelist import ModelWhitelist
from app.executor import subprocess_runner
from app.models.enums import JobStatus
from app.models.request import CreateJobRequest
from app.models.response import JobListResponse, JobLogResponse, JobResponse
from app.oc_config.generator import generate_config
from app.utils.ids import is_valid_job_id
from app.utils.time import now_iso

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _validate_request(req: CreateJobRequest) -> None:
    if not is_valid_job_id(req.job_id):
        raise HTTPException(422, f"invalid job_id format: {req.job_id}")

    for ds in req.datasets:
        item = ds.model_dump(exclude_none=True)
        if set(item.keys()) <= {"abbr"}:
            if not DatasetRegistry.is_builtin(ds.abbr):
                raise HTTPException(422, f"unknown builtin dataset: {ds.abbr}")
        else:
            try:
                DatasetWhitelist.validate_dataset_item(item)
            except ValueError as e:
                raise HTTPException(422, str(e)) from e

    for m in req.models:
        try:
            ModelWhitelist.validate(m.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e)) from e


def _read_log_window(
    log_path: Path,
    start_line: int,
    limit: int,
    tail: bool,
) -> tuple[list[str], int, int, bool]:
    """读日志文件一个窗口。返回 (lines, total_lines, effective_start_line, eof)。

    行定义：以 `\\n` 分隔。最后一个不完整行（文件结尾无换行）也计 1 行。
    """
    if not log_path.exists():
        return [], 0, start_line, True

    # 一次性读全文件 — OC 评测日志规模可控（任务级别，MB 级）
    # 后续如果单任务日志 > 100MB 再改成 seek+read 增量读。
    data = log_path.read_bytes()
    raw_lines = data.split(b"\n")
    # split(b"\n") 在文件以 \n 结尾时会多一个空 element，丢弃
    if raw_lines and raw_lines[-1] == b"":
        raw_lines.pop()
    total_lines = len(raw_lines)

    if tail:
        effective_start = max(0, total_lines - limit)
        end = total_lines
    else:
        # start_line 越界截断到合法范围
        effective_start = max(0, min(start_line, total_lines))
        end = min(effective_start + limit, total_lines)

    selected = raw_lines[effective_start:end]
    lines = [line.decode("utf-8", errors="replace") for line in selected]
    eof = end >= total_lines
    return lines, total_lines, effective_start, eof


@router.post("", status_code=201, response_model=JobResponse)
async def create_job(req: CreateJobRequest) -> JobResponse:
    # 延迟导入：避免与 app.main 的循环导入
    from app.main import get_instance_state, get_state_store

    store = get_state_store()
    inst = get_instance_state()

    _validate_request(req)

    if store.exists(req.job_id):
        raise HTTPException(409, f"job_id exists: {req.job_id}")
    if inst.is_at_capacity():
        raise HTTPException(503, "worker pool at capacity")

    if not await inst.try_acquire(req.job_id):
        raise HTTPException(503, "worker pool at capacity")

    try:
        config_path = await generate_config(req)
    except Exception as e:
        await inst.release(req.job_id)
        raise HTTPException(500, f"generate_config failed: {e}") from e

    work_dir = str(Path(config_path).parent.parent)

    # Phase 4: OC 子进程日志落盘路径
    #   layout: <oc_data_root>/workspace/_in_progress/<job_id>/<run_dir>/logs/opencompass.log
    #   run_dir 来自 generator.py 默认值 "run_001"（jobs.py 不传 run_dir），
    #   从 config_path 反推以避免与 generator 重复硬编码。
    log_path = (
        Path(config_path).parent.parent  # work_dir
        / Path(config_path).parent.name   # run_dir
        / "logs"
        / "opencompass.log"
    )

    initial = {
        "job_id": req.job_id,
        "status": JobStatus.STARTING.value,
        "instance_id": inst.instance_id,
        "datasets": [ds.model_dump(exclude_none=True) for ds in req.datasets],
        "models": [m.model_dump() for m in req.models],
        "config_path": config_path,
        "work_dir": work_dir,
        "log_path": str(log_path),
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "error_message": None,
        "pid": None,
        "created_by": req.created_by,
    }
    store.write_atomic(req.job_id, initial)

    try:
        proc = await subprocess_runner.start(req.job_id, config_path, log_path)
    except Exception as e:
        await inst.release(req.job_id)
        store.write_atomic(req.job_id, {
            **initial,
            "status": JobStatus.FAILED.value,
            "finished_at": now_iso(),
            "error_message": f"subprocess start failed: {e}",
        })
        raise HTTPException(500, f"subprocess start failed: {e}") from e

    inst.track_process(req.job_id, proc)
    store.write_atomic(req.job_id, {
        **initial,
        "status": JobStatus.RUNNING.value,
        "started_at": now_iso(),
        "pid": proc.pid,
    })

    # 异步终态化（不阻塞响应）
    asyncio.create_task(
        subprocess_runner.wait_and_finalize(req.job_id, proc, store, inst)
    )

    final_state = store.read(req.job_id) or initial
    return JobResponse(**final_state)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    # 延迟导入：避免与 app.main 的循环导入
    from app.main import get_state_store

    state = get_state_store().read(job_id)
    if state is None:
        raise HTTPException(404, "job not found")
    return JobResponse(**state)


@router.get("/{job_id}/log", response_model=JobLogResponse)
async def get_job_log(
    job_id: str,
    start_line: int = Query(0, ge=0, description="0-indexed starting line"),
    limit: int = Query(
        100, ge=1, le=1000, description="Max lines to return (capped at 1000)"
    ),
    tail: bool = Query(
        False, description="If true, return last `limit` lines (ignore start_line)"
    ),
) -> JobLogResponse:
    """任务日志分页读取（Phase 4）。

    按行分页：start_line + limit 定位窗口；tail=true 时忽略 start_line，返回最后 limit 行。
    访问权限与 GET /jobs/{id} 一致（任意实例可读，不检查 created_by）。
    log_path 来自 store 中 POST /jobs 时记录的路径。
    """
    from app.main import get_state_store

    state = get_state_store().read(job_id)
    if state is None:
        raise HTTPException(404, "job not found")

    log_path_str = state.get("log_path")
    if not log_path_str:
        # 老实例 / 旧版本未落盘 → 返回空 content
        return JobLogResponse(
            job_id=job_id,
            log_path="",
            total_lines=0,
            start_line=start_line,
            limit=limit,
            returned_lines=0,
            eof=True,
            lines=[],
        )

    log_path = Path(log_path_str)
    try:
        lines, total, eff_start, eof = _read_log_window(log_path, start_line, limit, tail)
    except OSError as e:
        raise HTTPException(500, f"read log failed: {e}") from e

    return JobLogResponse(
        job_id=job_id,
        log_path=str(log_path),
        total_lines=total,
        start_line=eff_start,
        limit=limit,
        returned_lines=len(lines),
        eof=eof,
        lines=lines,
    )


@router.post("/{job_id}/stop", status_code=202)
async def stop_job(job_id: str) -> dict:
    """任务停止：CAS 写 STARTING/RUNNING → CANCELLING，再 SIGTERM 进程。"""
    from app.main import get_instance_state, get_state_store

    store = get_state_store()
    inst = get_instance_state()

    current = store.read(job_id)
    if current is None:
        raise HTTPException(404, "job not found")

    if current.get("instance_id") != inst.instance_id:
        raise HTTPException(
            403, f"job owned by other instance: {current.get('instance_id')}"
        )

    if not can_stop(current.get("status", "")):
        raise HTTPException(
            409, f"cannot stop job in status {current.get('status')}"
        )

    ok = store.compare_and_swap(
        job_id,
        expected_status=current["status"],
        mutation={"status": JobStatus.CANCELLING.value},
    )
    if not ok:
        raise HTTPException(409, "already cancelling")

    proc = inst.get_process(job_id)
    if proc is not None:
        asyncio.create_task(subprocess_runner.request_cancel(proc))

    return {"job_id": job_id, "status": JobStatus.CANCELLING.value}


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: str | None = None,
    model_path: str | None = None,
    all: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> JobListResponse:
    """列出任务：filter + offset/limit 分页。"""
    from app.main import get_instance_state, get_state_store

    store = get_state_store()
    inst = get_instance_state()

    items = store.list_all()
    filtered: list[dict] = []
    for _, state in items:
        if not all and state.get("instance_id") != inst.instance_id:
            continue
        if status is not None and state.get("status") != status:
            continue
        if model_path is not None:
            models = state.get("models") or []
            if not any(model_path in (m.get("path") or "") for m in models):
                continue
        filtered.append(state)

    filtered.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    total = len(filtered)
    page = filtered[offset:offset + limit]
    return JobListResponse(
        items=[JobResponse(**s) for s in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str) -> None:
    """删除任务：仅终态允许。"""
    from app.main import get_state_store

    store = get_state_store()
    current = store.read(job_id)
    if current is None:
        raise HTTPException(404, "job not found")
    if not can_delete(current.get("status", "")):
        raise HTTPException(
            409, f"cannot delete in status {current.get('status')}"
        )
    store.delete(job_id)
