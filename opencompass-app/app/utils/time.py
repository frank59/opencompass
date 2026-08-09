from datetime import datetime, timezone


def now_iso() -> str:
    """UTC ISO8601，精确到微秒，例如 2026-08-09T10:30:00.523000Z。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
