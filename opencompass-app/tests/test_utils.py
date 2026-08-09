import pytest
from app.utils.ids import is_valid_job_id


@pytest.mark.parametrize(
    "job_id,expected",
    [
        ("job_20260808_abc123", True),
        ("abc-XYZ_0", True),
        ("a", True),
        ("a" * 64, True),
        ("", False),
        ("a" * 65, False),
        ("has space", False),
        ("has/slash", False),
        ("中文_abc", False),       # 只允许 ASCII
        ("job.with.dot", False),
        ("abc?", False),
    ],
)
def test_is_valid_job_id(job_id, expected):
    assert is_valid_job_id(job_id) == expected
