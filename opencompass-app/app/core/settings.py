"""pydantic-settings 单例：从环境变量读取服务配置。"""
import os
import socket
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


@lru_cache(maxsize=1)
def derive_instance_id(explicit: str | None = None) -> str:
    """派生实例 ID；显式传入时优先使用。"""
    if explicit:
        return explicit
    hostname = socket.gethostname()
    port = os.environ.get("PORT", "8080")
    return f"{hostname}:{port}"


class Settings(BaseSettings):
    """通过环境变量配置本实例。"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    instance_id: str = ""
    oc_data_root: str = "/data/opencompass"
    max_concurrent: int = 8
    log_level: str = "INFO"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # INSTANCE_ID 走显式派生（需要 socket 调用）
        env_iid = os.environ.get("INSTANCE_ID")
        # 优先用 env 中的 INSTANCE_ID，否则用 hostname:port 回退
        if env_iid:
            self.instance_id = env_iid
        else:
            self.instance_id = derive_instance_id()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
