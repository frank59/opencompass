from enum import Enum


class JobStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
