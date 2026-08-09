"""Dataset 注册表：从 dataset-index.yml 解析 abbr → (module_path, var_name)。

例：{"gsm8k": ("opencompass.configs.datasets.gsm8k.gsm8k_gen", "gsm8k_datasets")}

用法：
    mod, var = DatasetRegistry.resolve_builtin("gsm8k")
    # 在 config 文件里写：from opencompass.configs.datasets.gsm8k.gsm8k_gen import gsm8k_datasets
"""
from pathlib import Path

import yaml

# 测试时可被 monkeypatch 替换的实际索引文件路径。
_DATASET_INDEX_PATH: Path = Path(__file__).parent.parent / "data" / "dataset_index.yaml"


class DatasetRegistry:
    _INDEX: dict[str, tuple[str, str]] | None = None

    @classmethod
    def _load_with_path(cls, path: Path) -> dict[str, tuple[str, str]]:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or []
        idx: dict[str, tuple[str, str]] = {}
        for entry in raw:
            (abbr, info), = entry.items()
            cfg_path = info["configpath"]
            # 部分条目（longbench / teval / lawbench）以 list 提供多语言/多任务变体。
            # MVP 取首个作为规范 path。
            if isinstance(cfg_path, list):
                cfg_path = cfg_path[0]
            module_path = cfg_path.removesuffix(".py").replace("/", ".")
            var_name = f"{Path(cfg_path).parent.name}_datasets"
            idx[abbr] = (module_path, var_name)
        return idx

    @classmethod
    def _load(cls) -> dict[str, tuple[str, str]]:
        if cls._INDEX is not None:
            return cls._INDEX
        cls._INDEX = cls._load_with_path(_DATASET_INDEX_PATH)
        return cls._INDEX

    @classmethod
    def is_builtin(cls, abbr: str) -> bool:
        return abbr in cls._load()

    @classmethod
    def resolve_builtin(cls, abbr: str) -> tuple[str, str]:
        idx = cls._load()
        if abbr not in idx:
            raise KeyError(f"dataset '{abbr}' not in registry")
        return idx[abbr]
