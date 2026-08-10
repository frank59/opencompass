"""任务创建 + 查询。"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.dataset_registry import DatasetRegistry
from app.core.dataset_whitelist import DatasetWhitelist
from app.core.job_state_machine import can_stop
from app.core.model_whitelist import ModelWhitelist
from app.executor import subprocess_runner
from app.models.enums import JobStatus
from app.models.request import CreateJobRequest
from app.models.response import JobResponse
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

    initial = {
        "job_id": req.job_id,
        "status": JobStatus.STARTING.value,
        "instance_id": inst.instance_id,
        "datasets": [ds.model_dump(exclude_none=True) for ds in req.datasets],
        "models": [m.model_dump() for m in req.models],
        "config_path": config_path,
        "work_dir": work_dir,
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
        proc = await subprocess_runner.start(req.job_id, config_path)
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
