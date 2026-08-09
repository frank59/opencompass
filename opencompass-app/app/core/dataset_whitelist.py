"""Dataset 白名单：覆盖 5 个字段位置 —— dataset.type 与四个子组件 type。

白名单通过扫描 OpenCompass 的 registry 动态发现：
- LOAD_DATASET._module_dict → dataset.type
- ICL_EVALUATORS._module_dict → eval_cfg.evaluator.type
- ICL_INFERENCERS._module_dict → infer_cfg.inferencer.type
- icl_retriever._module_dict → infer_cfg.retriever.type
- prompt_template 相关注册表（OC 内部略有差异，缺则回退 empty）

NOTE: 不写死类型名 —— 一律从 OC 注册表读取。
"""
import logging

log = logging.getLogger(__name__)


def _scan_keys(registry_attr: str) -> frozenset[str]:
    """从 opencompass.registry 的注册表中读 _module_dict 的 key 集合。"""
    try:
        from opencompass.registry import Registry
        reg = Registry._module_dict  # 实际访问点
        # registry 是 dict[str, ...] 形式。registry_attr 用作日志标签。
        return frozenset(reg.keys())
    except Exception:
        return frozenset()


class DatasetWhitelist:
    """5 字段覆盖 + 自定义数据集 path 校验。"""
    _DATASET: frozenset[str] | None = None
    _EVAL: frozenset[str] | None = None
    _INFER: frozenset[str] | None = None
    _RETRIEVER: frozenset[str] | None = None
    _PROMPT: frozenset[str] | None = None

    # -------------------- dataset.types --------------------
    @classmethod
    def dataset_types(cls) -> frozenset[str]:
        if cls._DATASET is None:
            try:
                from opencompass.registry import LOAD_DATASET
                cls._DATASET = frozenset(LOAD_DATASET._module_dict.keys())
            except Exception:
                cls._DATASET = frozenset()
        return cls._DATASET

    # -------------------- evaluator.types --------------------
    @classmethod
    def evaluator_types(cls) -> frozenset[str]:
        if cls._EVAL is None:
            try:
                from opencompass.registry import ICL_EVALUATORS
                cls._EVAL = frozenset(ICL_EVALUATORS._module_dict.keys())
            except Exception:
                cls._EVAL = frozenset()
        return cls._EVAL

    # -------------------- inferencer.types --------------------
    @classmethod
    def inferencer_types(cls) -> frozenset[str]:
        if cls._INFER is None:
            try:
                from opencompass.registry import ICL_INFERENCERS
                cls._INFER = frozenset(ICL_INFERENCERS._module_dict.keys())
            except Exception:
                cls._INFER = frozenset()
        return cls._INFER

    # -------------------- retriever.types --------------------
    @classmethod
    def retriever_types(cls) -> frozenset[str]:
        if cls._RETRIEVER is None:
            try:
                from opencompass.openicl.icl_retriever import _module_dict as retriever_dict
                cls._RETRIEVER = frozenset(retriever_dict.keys())
            except Exception:
                cls._RETRIEVER = frozenset()
        return cls._RETRIEVER

    # -------------------- prompt_template.types --------------------
    @classmethod
    def prompt_template_types(cls) -> frozenset[str]:
        if cls._PROMPT is None:
            try:
                from opencompass.openicl.icl_prompt_template import _module_dict as pt_dict
                cls._PROMPT = frozenset(pt_dict.keys())
            except Exception:
                cls._PROMPT = frozenset()
        return cls._PROMPT

    # -------------------- validation --------------------
    @classmethod
    def validate_dataset_item(cls, ds: dict) -> None:
        if not isinstance(ds, dict):
            raise ValueError("dataset item must be a dict")
        if not ds.get("abbr"):
            raise ValueError("missing 'abbr' field")

        # 自定义数据集走白名单
        type_str = ds.get("type")
        if type_str not in cls.dataset_types():
            raise ValueError(f"dataset type '{type_str}' not in whitelist")

        path = ds.get("path", "")
        if not path.startswith("/data/opencompass/datasets/customer/"):
            raise ValueError(
                f"path must start with /data/opencompass/datasets/customer/, got: {path}"
            )

        cls._validate_subtype(ds, "infer_cfg", "prompt_template", cls.prompt_template_types())
        cls._validate_subtype(ds, "infer_cfg", "retriever", cls.retriever_types())
        cls._validate_subtype(ds, "infer_cfg", "inferencer", cls.inferencer_types())
        cls._validate_subtype(ds, "eval_cfg", "evaluator", cls.evaluator_types())

    @staticmethod
    def _validate_subtype(ds: dict, section: str, key: str, allowed: frozenset[str]) -> None:
        sub_type = (ds.get(section) or {}).get(key, {}).get("type")
        if sub_type and sub_type not in allowed:
            raise ValueError(f"{section}.{key}.type '{sub_type}' not in whitelist")
