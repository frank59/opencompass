from app.models.enums import JobStatus


def test_job_status_values():
    expected = {
        "starting", "running", "finalizing", "completed", "failed",
        "cancelling", "cancelled",
    }
    actual = {s.value for s in JobStatus}
    assert actual == expected


def test_job_status_is_str():
    assert isinstance(JobStatus.RUNNING, str)
    assert JobStatus.RUNNING == "running"


def test_cancelling_and_cancelled_are_str():
    assert JobStatus.CANCELLING == "cancelling"
    assert JobStatus.CANCELLED == "cancelled"
    assert isinstance(JobStatus.CANCELLING, str)
