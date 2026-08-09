import re

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_valid_job_id(job_id: str) -> bool:
    """校验 job_id 格式：ASCII 字母/数字/下划线/连字符，长度 1~64。"""
    return bool(_JOB_ID_RE.match(job_id))
