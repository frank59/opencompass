import asyncio
from pathlib import Path

from app.core.dataset_registry import DatasetRegistry
from app.models.request import CreateJobRequest, DatasetItem, ModelItem
from app.oc_config.generator import generate_config


def _make_req(abbr: str = "gsm8k", path: str = "qwen") -> CreateJobRequest:
    return CreateJobRequest(
        job_id="job_test_001",
        datasets=[DatasetItem(abbr=abbr)],
        models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path=path)],
    )


def test_builtin_dataset_renders_from_import(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text(
        "- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(DatasetRegistry, "_INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    req = _make_req()
    path = asyncio.run(generate_config(req))
    assert Path(path).exists()
    text = Path(path).read_text(encoding="utf-8")
    assert (
        "from opencompass.configs.datasets.gsm8k.gsm8k_gen import gsm8k_datasets"
        in text
    )
    assert "with read_base():" in text
    assert "datasets = gsm8k_datasets" in text
    assert "models = [model_qwen_0]" in text


def test_multi_dataset_concatenates_aliases(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text(
        "- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n"
        "- mmlu:\n    configpath: opencompass/configs/datasets/mmlu/mmlu_gen.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(DatasetRegistry, "_INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    req = CreateJobRequest(
        job_id="job_x",
        datasets=[DatasetItem(abbr="gsm8k"), DatasetItem(abbr="mmlu")],
        models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path="qwen")],
    )
    path = asyncio.run(generate_config(req))
    text = Path(path).read_text(encoding="utf-8")
    assert "datasets = gsm8k_datasets + mmlu_datasets" in text


def test_atomic_write_uses_replace(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text(
        "- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(DatasetRegistry, "_INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    import app.oc_config.generator as gen_mod

    calls = []
    real_replace = gen_mod.os.replace

    def spy_replace(src, dst):
        calls.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(gen_mod.os, "replace", spy_replace)

    req = CreateJobRequest(
        job_id="job_atom",
        datasets=[DatasetItem(abbr="gsm8k")],
        models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path="qwen")],
    )
    asyncio.run(generate_config(req))
    assert len(calls) == 1
    src, dst = calls[0]
    assert str(src).endswith(".py.tmp")
    assert str(dst).endswith("job_atom.py")


def test_rendered_file_lives_under_in_progress_dir(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text(
        "- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(DatasetRegistry, "_INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    req = CreateJobRequest(
        job_id="job_layout",
        datasets=[DatasetItem(abbr="gsm8k")],
        models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path="qwen")],
    )
    path = asyncio.run(generate_config(req))
    expected = (
        Path(tmp_path)
        / "oc-root"
        / "workspace"
        / "_in_progress"
        / "job_layout"
        / "run_001"
        / "configs"
        / "job_layout.py"
    )
    assert Path(path) == expected


def test_generator_handles_model_alias_safe_chars(tmp_path, monkeypatch):
    """model.path 含特殊字符时也应合法输出。"""
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text(
        "- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(DatasetRegistry, "_INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    req = CreateJobRequest(
        job_id="job_safe_chars",
        datasets=[DatasetItem(abbr="gsm8k")],
        models=[
            ModelItem(
                type="opencompass.models.openai_api.OpenAISDK",
                path="qwen-7b/special",
                key="sk-test",
            )
        ],
    )
    path = asyncio.run(generate_config(req))
    text = Path(path).read_text(encoding="utf-8")
    # 模型别名应只用合法标识符字符（用 _ 替换 - 和 /）
    assert "model_qwen_7b_special_" in text
