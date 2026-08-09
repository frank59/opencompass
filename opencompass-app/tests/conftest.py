"""全局 pytest fixture。所有测试默认使用隔离 tmp 目录 + pytest-instance 标识。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """每个测试隔离：OC_DATA_ROOT → tmp_path/oc-root；INSTANCE_ID → pytest-instance。"""
    # 清空 get_settings() 的 lru_cache (避免跨测试缓存旧 oc_data_root)
    from app.core.settings import get_settings
    get_settings.cache_clear()

    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))
    monkeypatch.setenv("INSTANCE_ID", "pytest-instance")
    monkeypatch.setenv("MAX_CONCURRENT", "4")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    """FastAPI TestClient（已在 _isolate_env 中隔离环境）。"""
    from app.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
