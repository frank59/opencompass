"""实例启动时扫描遗留任务并收尾。

设计要点：
- 在 lifespan startup 单线程上下文串行执行，避免 PID 复用风险
- 单文件失败不阻断整个 recover（依赖 list_all 跳过损坏文件）
"""
import logging
import os

from app.core.state import InstanceState
from app.models.enums import JobStatus
from app.stores.nfs_state import JobStateStore
from app.utils.time import now_iso

log = logging.getLogger(__name__)


def is_pid_in_current_session(pid: int | None) -> bool:
    """检查 PID 是否属于当前进程会话。

    实现：os.kill(pid, 0) — 仅检查进程是否存在。lifespan startup 串行执行
    窗口期（<3s）内 PID 复用概率可忽略。
    """
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


async def recover_after_restart(
    store: JobStateStore,
    instance: InstanceState,
) -> None:
    """实例启动时扫描遗留任务并收尾（PRD FR-6.1~6.5）。

    处理规则：
      - starting         → failed（实例在启动子进程前崩溃）
      - running          → PID 不在新会话 → failed
      - cancelling       → PID 不在新会话 → failed
      - finalizing       → failed（不重跑 summarizer，PRD 推迟）
      - terminal         → 跳过
    """
    for job_id, state in store.list_all():
        if state.get("instance_id") != instance.instance_id:
            continue  # 别人的任务不归我管

        status = state.get("status")
        if status in (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        ):
            continue

        if status == JobStatus.STARTING.value:
            await _mark_failed(store, instance, job_id, state,
                               "Instance crashed before subprocess started")
        elif status in (JobStatus.RUNNING.value, JobStatus.CANCELLING.value):
            pid = state.get("pid")
            if not is_pid_in_current_session(pid):
                await _mark_failed(store, instance, job_id, state,
                                   f"Instance crashed; PID {pid} not in current session")
            else:
                log.warning("Job %s PID %s still alive after restart; leaving for ops",
                            job_id, pid)
        elif status == JobStatus.FINALIZING.value:
            await _mark_failed(store, instance, job_id, state,
                               "Instance crashed during finalization")
        else:
            log.warning("Unknown status %s for job %s; skipping", status, job_id)


async def _mark_failed(store, instance, job_id, current, error_message):
    """标记任务为 failed 并对齐 slot 计数。"""
    new_state = {
        **current,
        "status": JobStatus.FAILED.value,
        "finished_at": now_iso(),
        "error_message": error_message,
    }
    try:
        store.write_atomic(job_id, new_state)
    except Exception:
        log.exception("Failed to write recovered state for job %s", job_id)
        return  # 单文件失败不阻断

    instance.reserve_for_recovery(job_id)
    await instance.release(job_id)
    log.info("Recovered job %s: %s", job_id, error_message)
