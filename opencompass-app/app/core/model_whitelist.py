"""Model 白名单：动态扫描 OpenCompass 的 BaseAPIModel 子类。

白名单绝不硬编码类名；通过 `dir(opencompass.models)` + `issubclass(..., BaseAPIModel)` 动态发现。
opencompass 未安装时回退为 empty frozenset（仅本地开发 / 测试用）。
"""
import logging

log = logging.getLogger(__name__)


class ModelWhitelist:
    _TYPES: frozenset[str] | None = None

    @classmethod
    def _scan(cls) -> frozenset[str]:
        """实际扫描函数；测试可 monkeypatch。"""
        try:
            import opencompass.models as pkg  # noqa: F401
            from opencompass.models.base_api import BaseAPIModel
            found: set[str] = set()
            for name in dir(pkg):
                obj = getattr(pkg, name)
                if isinstance(obj, type) and issubclass(obj, BaseAPIModel) and obj is not BaseAPIModel:
                    found.add(f"opencompass.models.{obj.__name__}")
            return frozenset(found)
        except ImportError:
            log.warning("opencompass not installed; model whitelist empty")
            return frozenset()

    @classmethod
    def types(cls) -> frozenset[str]:
        if cls._TYPES is not None:
            return cls._TYPES
        cls._TYPES = cls._scan()
        return cls._TYPES

    @classmethod
    def validate(cls, model_dict: dict) -> None:
        if not model_dict.get("type"):
            raise ValueError("missing 'type' field")
        if not model_dict.get("path"):
            raise ValueError("missing 'path' field")
        if model_dict["type"] not in cls.types():
            raise ValueError(f"model type '{model_dict['type']}' not in whitelist")
