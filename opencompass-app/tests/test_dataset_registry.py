
import pytest

from app.core.dataset_registry import _DATASET_INDEX_PATH, DatasetRegistry


def test_load_returns_dict_with_abbr_keys():
    DatasetRegistry._INDEX = None
    idx = DatasetRegistry._load()
    assert isinstance(idx, dict)
    assert "gsm8k" in idx


def test_resolve_builtin_gsm8k_returns_module_and_var():
    DatasetRegistry._INDEX = None
    mod, var = DatasetRegistry.resolve_builtin("gsm8k")
    assert mod == "opencompass.configs.datasets.gsm8k.gsm8k_gen"
    assert var == "gsm8k_datasets"


def test_is_builtin_unknown_returns_false():
    DatasetRegistry._INDEX = None
    assert DatasetRegistry.is_builtin("definitely_not_a_real_dataset_xyzzy") is False


def test_resolve_builtin_unknown_raises():
    DatasetRegistry._INDEX = None
    with pytest.raises(KeyError, match="not in registry"):
        DatasetRegistry.resolve_builtin("no_such_dataset_xyz")


def test_load_is_cached_after_first_call(monkeypatch):
    DatasetRegistry._INDEX = None
    DatasetRegistry._load()
    # mutate dict：验证第二次调用返回相同引用（缓存）
    DatasetRegistry._INDEX["poison"] = ("a", "b")
    second = DatasetRegistry._load()
    assert "poison" in second


def test_load_with_path_supports_alternate_file(tmp_path):
    fake = tmp_path / "fake_index.yaml"
    fake.write_text("- myds:\n    configpath: pkg/mydir/myds_gen.py\n", encoding="utf-8")
    out = DatasetRegistry._load_with_path(fake)
    assert "myds" in out
    assert out["myds"] == ("pkg.mydir.myds_gen", "mydir_datasets")


def test_dataset_index_path_default():
    p = _DATASET_INDEX_PATH
    assert p.name == "dataset_index.yaml"
    assert str(p).endswith("data/dataset_index.yaml")
