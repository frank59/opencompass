"""全局 pytest fixture。所有测试默认使用隔离 tmp 目录 + pytest-instance 标识。"""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """每个测试隔离：OC_DATA_ROOT → tmp_path/oc-root；INSTANCE_ID → pytest-instance。"""
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))
    monkeypatch.setenv("INSTANCE_ID", "pytest-instance")
    monkeypatch.setenv("MAX_CONCURRENT", "4")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    yield
