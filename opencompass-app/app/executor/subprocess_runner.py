"""OpenCompass subprocess 执行器。

参数布局（与设计文档 §6.11 / §8.1 一致）：
    config_path = .../<job_id>/<run_dir>/configs/<job_id>.py
    -w 指向    = .../<job_id>/
    -r 指向    = <run_dir>
"""
import asyncio
from pathlib import Path

from app.core.state import InstanceState
from app.stores.nfs_state import JobStateStore
from app.utils.time import now_iso


async def start(job_id: str, config_path: str) -> asyncio.subprocess.Process:
    """按规范构造 opencompass 子进程命令并启动。返回进程对象。"""
    config_p = Path(config_path)
    run_dir = config_p.parent.parent
    cmd = [
        "opencompass",
        config_path,
        "-w",
        str(run_dir.parent),
        "-r",
        run_dir.name,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    return proc


async def request_cancel(proc, grace_seconds: int = 30) -> None:
    """SIGTERM → 异步等 grace → SIGKILL。best-effort 强制结束。"""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        # best-effort：SIGKILL 后回收僵尸，进程死/异常状态都吞
        try:
            await proc.wait()
        except Exception:
            pass


async def wait_and_finalize(
    job_id: str,
    proc: asyncio.subprocess.Process,
    state_store: JobStateStore,
    instance_state: InstanceState,
) -> None:
    """等待进程退出，把状态收敛到 completed/failed，最后释放 worker 槽。"""
    rc = await proc.wait()
    current = state_store.read(job_id)
    if current is None:
        await instance_state.release(job_id)
        return

    final_status = "completed" if rc == 0 else "failed"
    state_store.write_atomic(job_id, {
        **current,
        "status": final_status,
        "finished_at": now_iso(),
        "exit_code": rc,
        "error_message": None if rc == 0 else f"opencompass exit {rc}",
    })
    await instance_state.release(job_id)
