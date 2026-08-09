from app.models.enums import JobStatus


def test_job_status_values():
    assert JobStatus.STARTING.value == "starting"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.FINALIZING.value == "finalizing"
    assert JobStatus.COMPLETED.value == "completed"
    assert JobStatus.FAILED.value == "failed"


def test_job_status_is_str():
    assert isinstance(JobStatus.RUNNING, str)
    assert JobStatus.RUNNING == "running"


def test_job_status_no_cancelling():
    """MVP 不含 CANCELLING/CANCELLED（Phase 2 再加）。"""
    assert not hasattr(JobStatus, "CANCELLING")
    assert not hasattr(JobStatus, "CANCELLED")
