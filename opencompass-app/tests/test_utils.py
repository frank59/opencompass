import pytest
from app.utils.ids import is_valid_job_id
from app.utils.time import now_iso
import re


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


def test_now_iso_format():
    s = now_iso()
    # 形如 2026-08-09T10:30:00.523000Z
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", s)


def test_now_iso_is_utc():
    """两次调用应严格非递减。"""
    a = now_iso()
    b = now_iso()
    assert a <= b
