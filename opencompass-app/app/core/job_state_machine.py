"""JobStatus 状态机迁移表。

集中所有 'from → to' 合法迁移，便于 (a) 校验状态变更 (b) 文档化。
"""
from app.models.enums import JobStatus


# 起始态：STARTING / RUNNING
STARTING_OR_RUNNING = {JobStatus.STARTING.value, JobStatus.RUNNING.value}

# 终态：COMPLETED / FAILED / CANCELLED
TERMINAL = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}


def can_stop(status: str) -> bool:
    """POST /stop 接受的状态：STARTING / RUNNING。"""
    return status in STARTING_OR_RUNNING


def can_delete(status: str) -> bool:
    """DELETE 接受的状态：终态。"""
    return status in TERMINAL