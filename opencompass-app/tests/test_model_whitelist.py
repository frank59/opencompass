import pytest

from app.core.model_whitelist import ModelWhitelist


def setup_function(fn):
    """每个用例前清空缓存。"""
    ModelWhitelist._TYPES = None


def test_validate_missing_type():
    with pytest.raises(ValueError, match="type"):
        ModelWhitelist.validate({"path": "x"})


def test_validate_missing_path():
    with pytest.raises(ValueError, match="path"):
        ModelWhitelist.validate({"type": "x"})


def test_validate_unknown_type():
    ModelWhitelist._TYPES = frozenset({"opencompass.models.openai_api.OpenAISDK"})
    with pytest.raises(ValueError, match="not in whitelist"):
        ModelWhitelist.validate({"type": "not.In.Whitelist", "path": "qwen"})


def test_validate_known_type_passes():
    ModelWhitelist._TYPES = frozenset({"opencompass.models.openai_api.OpenAISDK"})
    ModelWhitelist.validate({"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"})


def test_types_returns_frozenset():
    ModelWhitelist._TYPES = frozenset({"a", "b"})
    assert isinstance(ModelWhitelist.types(), frozenset)
    assert ModelWhitelist.types() == frozenset({"a", "b"})


def test_types_empty_when_oc_not_installed(monkeypatch):
    """模拟 opencompass.models 不可导入 → 应回退为 empty frozenset。"""
    import importlib

    # 通过直接 monkeypatch scan 函数返回空集
    def fake_scan():
        return frozenset()
    monkeypatch.setattr(ModelWhitelist, "_scan", classmethod(lambda cls: fake_scan()))
    ModelWhitelist._TYPES = None
    assert ModelWhitelist.types() == frozenset()
