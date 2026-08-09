import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.dataset_registry import DatasetRegistry
from app.core.dataset_whitelist import DatasetWhitelist
from app.core.model_whitelist import ModelWhitelist
from app.main import create_app


@pytest.fixture
def fake_yaml(tmp_path):
    p = tmp_path / "di.yaml"
    p.write_text(
        "- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def client(fake_yaml, monkeypatch):
    DatasetRegistry._INDEX = DatasetRegistry._load_with_path(fake_yaml)
    monkeypatch.setattr(
        ModelWhitelist,
        "_TYPES",
        frozenset({"opencompass.models.openai_api.OpenAISDK"}),
    )
    monkeypatch.setattr(
        DatasetWhitelist,
        "_DATASET",
        frozenset({"opencompass.datasets.custom.CustomDataset"}),
    )
    monkeypatch.setattr(DatasetWhitelist, "_EVAL", frozenset({"AccEvaluator"}))
    monkeypatch.setattr(DatasetWhitelist, "_INFER", frozenset({"GenInferencer"}))
    monkeypatch.setattr(DatasetWhitelist, "_RETRIEVER", frozenset({"ZeroRetriever"}))
    monkeypatch.setattr(DatasetWhitelist, "_PROMPT", frozenset({"PromptTemplate"}))

    import app.executor.subprocess_runner as sr

    async def fake_start(job_id, config_path):
        proc = AsyncMock()
        proc.pid = 99999
        proc.wait = AsyncMock(return_value=0)
        return proc

    monkeypatch.setattr(sr, "start", fake_start)

    app = create_app()
    with TestClient(app) as c:
        yield c

    DatasetRegistry._INDEX = None


def test_post_jobs_201_with_builtin_dataset(client):
    req = {
        "job_id": "job_20260808_abc",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{
            "type": "opencompass.models.openai_api.OpenAISDK",
            "path": "qwen", "key": "sk-test",
        }],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "running"
    assert body["job_id"] == "job_20260808_abc"


def test_post_jobs_409_when_duplicate(client):
    req = {
        "job_id": "job_dup",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    res1 = client.post("/api/v1/jobs", json=req)
    assert res1.status_code == 201
    res2 = client.post("/api/v1/jobs", json=req)
    assert res2.status_code == 409


def test_post_jobs_422_unknown_builtin(client):
    req = {
        "job_id": "job_z",
        "datasets": [{"abbr": "definitely_not_a_real_dataset_xyzzy"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 422


def test_post_jobs_422_when_model_type_not_in_whitelist(client):
    req = {
        "job_id": "job_w",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "not.In.Whitelist", "path": "qwen"}],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 422


def test_get_job_200_after_create(client):
    req = {
        "job_id": "job_get_200",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    client.post("/api/v1/jobs", json=req)
    res = client.get("/api/v1/jobs/job_get_200")
    assert res.status_code == 200
    body = res.json()
    assert body["job_id"] == "job_get_200"
    assert body["status"] in ("running", "completed")


def test_get_job_404(client):
    res = client.get("/api/v1/jobs/no_such_job_id_xyz")
    assert res.status_code == 404


def test_post_jobs_503_when_at_capacity(client, monkeypatch):
    from app import main as app_main
    for i in range(app_main.instance_state.max_concurrent):
        asyncio.run(app_main.instance_state.try_acquire(f"slot_{i}"))
    req = {
        "job_id": "job_overflow",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 503
