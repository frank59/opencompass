from app.core.job_state_machine import can_delete, can_stop
from app.models.enums import JobStatus


def test_can_stop_accepts_starting_running():
    assert can_stop(JobStatus.STARTING.value) is True
    assert can_stop(JobStatus.RUNNING.value) is True


def test_can_stop_rejects_others():
    for s in (JobStatus.FINALIZING, JobStatus.COMPLETED, JobStatus.FAILED,
              JobStatus.CANCELLING, JobStatus.CANCELLED):
        assert can_stop(s.value) is False, s


def test_can_delete_accepts_terminal():
    for s in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        assert can_delete(s.value) is True, s


def test_can_delete_rejects_non_terminal():
    for s in (JobStatus.STARTING, JobStatus.RUNNING, JobStatus.FINALIZING,
              JobStatus.CANCELLING):
        assert can_delete(s.value) is False, s