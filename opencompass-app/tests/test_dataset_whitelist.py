import pytest

from app.core.dataset_whitelist import DatasetWhitelist


@pytest.fixture(autouse=True)
def reset_whitelist():
    DatasetWhitelist._DATASET = None
    DatasetWhitelist._EVAL = None
    DatasetWhitelist._INFER = None
    DatasetWhitelist._RETRIEVER = None
    DatasetWhitelist._PROMPT = None
    yield
    DatasetWhitelist._DATASET = None
    DatasetWhitelist._EVAL = None
    DatasetWhitelist._INFER = None
    DatasetWhitelist._RETRIEVER = None
    DatasetWhitelist._PROMPT = None


@pytest.fixture
def populated():
    DatasetWhitelist._DATASET = frozenset({"Dataset1"})
    DatasetWhitelist._EVAL = frozenset({"Eval1"})
    DatasetWhitelist._INFER = frozenset({"Infer1"})
    DatasetWhitelist._RETRIEVER = frozenset({"Retr1"})
    DatasetWhitelist._PROMPT = frozenset({"Prompt1"})


def test_validate_missing_abbr():
    with pytest.raises(ValueError, match="abbr"):
        DatasetWhitelist.validate_dataset_item({})


def test_validate_subtype_inferencer(populated):
    ds = {
        "abbr": "x",
        "type": "Dataset1",
        "path": "/data/opencompass/datasets/customer/x.jsonl",
        "infer_cfg": {"inferencer": {"type": "EvilInferencer"}},
    }
    with pytest.raises(ValueError, match="infer_cfg.inferencer.type"):
        DatasetWhitelist.validate_dataset_item(ds)


def test_validate_subtype_evaluator(populated):
    ds = {
        "abbr": "x",
        "type": "Dataset1",
        "path": "/data/opencompass/datasets/customer/x.jsonl",
        "eval_cfg": {"evaluator": {"type": "EvilEvaluator"}},
    }
    with pytest.raises(ValueError, match="eval_cfg.evaluator.type"):
        DatasetWhitelist.validate_dataset_item(ds)


def test_validate_path_prefix(populated):
    ds = {
        "abbr": "x",
        "type": "Dataset1",
        "path": "/wrong/prefix/data/x.jsonl",
    }
    with pytest.raises(ValueError, match="path must start with"):
        DatasetWhitelist.validate_dataset_item(ds)


def test_validate_valid_dataset_passes(populated):
    ds = {
        "abbr": "x",
        "type": "Dataset1",
        "path": "/data/opencompass/datasets/customer/x.jsonl",
        "reader_cfg": {"input_columns": ["question"]},
        "infer_cfg": {
            "prompt_template": {"type": "Prompt1"},
            "retriever": {"type": "Retr1"},
            "inferencer": {"type": "Infer1"},
        },
        "eval_cfg": {"evaluator": {"type": "Eval1"}},
    }
    DatasetWhitelist.validate_dataset_item(ds)  # 不抛错


def test_validate_unknown_dataset_type(populated):
    ds = {
        "abbr": "x",
        "type": "EvilDataset",
        "path": "/data/opencompass/datasets/customer/x.jsonl",
    }
    with pytest.raises(ValueError, match="dataset type"):
        DatasetWhitelist.validate_dataset_item(ds)
