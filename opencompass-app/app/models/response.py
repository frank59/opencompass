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
