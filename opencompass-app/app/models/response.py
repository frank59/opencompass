from pydantic import BaseModel

from app.models.enums import JobStatus
from app.models.request import DatasetItem, ModelItem


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    instance_id: str
    datasets: list[DatasetItem]
    models: list[ModelItem]
    config_path: str
    work_dir: str
    log_path: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    pid: int | None = None
    created_by: str | None = None
    cancelled_by: str | None = None


class FreeWorkerCount(BaseModel):
    available: int
    max: int
    running: int


class HealthCheck(BaseModel):
    status: str
    checks: dict[str, str]


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int


class JobLogResponse(BaseModel):
    """任务日志分页读取响应（Phase 4）。

    lines 按行返回文本（UTF-8，decode 失败用 U+FFFD 替换）。
    start_line 是返回内容在文件中的起始行号（0-indexed）。
    total_lines 是文件总行数（含已读 + 未读）。
    eof=True 表示本次返回到达文件末尾。
    """
    job_id: str
    log_path: str
    total_lines: int
    start_line: int
    limit: int
    returned_lines: int
    eof: bool
    lines: list[str]
