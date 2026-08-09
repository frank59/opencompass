"""INSTANCE_ID 派生（移出 settings.py 降低耦合）。"""
import os
import socket
from functools import lru_cache


@lru_cache(maxsize=1)
def derive_instance_id(explicit: str | None = None) -> str:
    """派生实例 ID；显式传入时优先使用。

    例：
        derive_instance_id() -> "myserver:8080"
        derive_instance_id("custom-id") -> "custom-id"
    """
    if explicit:
        return explicit
    hostname = socket.gethostname()
    port = os.environ.get("PORT", "8080")
    return f"{hostname}:{port}"
