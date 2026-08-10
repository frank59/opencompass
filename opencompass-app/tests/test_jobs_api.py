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

    async def fake_wait_and_finalize(*args, **kwargs):
        # noop: 让状态保持 running，避免后续 stop / list 测试被完成态干扰
        pass

    monkeypatch.setattr(sr, "start", fake_start)
    monkeypatch.setattr(sr, "wait_and_finalize", fake_wait_and_finalize)

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


def test_post_stop_202_sets_status_cancelling(client):
    req = {
        "job_id": "job_s1",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    r = client.post("/api/v1/jobs", json=req)
    assert r.status_code == 201
    res = client.post("/api/v1/jobs/job_s1/stop")
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "cancelling"
    assert body["job_id"] == "job_s1"


def test_post_stop_403_when_other_instance(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    store.write_atomic("job_other", {
        "job_id": "job_other", "status": JobStatus.RUNNING.value,
        "instance_id": "OTHER-INSTANCE", "datasets": [], "models": [],
        "config_path": "/x", "work_dir": "/y", "created_at": now_iso(),
        "started_at": now_iso(), "finished_at": None, "exit_code": None,
        "error_message": None, "pid": None, "created_by": None,
    })
    res = client.post("/api/v1/jobs/job_other/stop")
    assert res.status_code == 403
    assert "OTHER-INSTANCE" in res.text


def test_post_stop_404_when_not_found(client):
    res = client.post("/api/v1/jobs/no_such_job_xyz/stop")
    assert res.status_code == 404


def test_post_stop_409_when_completed(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    store.write_atomic("job_done", {
        "job_id": "job_done", "status": JobStatus.COMPLETED.value,
        "instance_id": app_main.instance_state.instance_id,
        "datasets": [], "models": [], "config_path": "/x", "work_dir": "/y",
        "created_at": now_iso(), "started_at": now_iso(),
        "finished_at": now_iso(), "exit_code": 0, "error_message": None,
        "pid": None, "created_by": None,
    })
    res = client.post("/api/v1/jobs/job_done/stop")
    assert res.status_code == 409


def test_post_stop_409_when_already_cancelling(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    store.write_atomic("job_cancelling", {
        "job_id": "job_cancelling", "status": JobStatus.CANCELLING.value,
        "instance_id": app_main.instance_state.instance_id,
        "datasets": [], "models": [], "config_path": "/x", "work_dir": "/y",
        "created_at": now_iso(), "started_at": now_iso(),
        "finished_at": None, "exit_code": None, "error_message": None,
        "pid": None, "created_by": None,
    })
    res = client.post("/api/v1/jobs/job_cancelling/stop")
    assert res.status_code == 409


def test_get_jobs_list_returns_only_owned_when_all_false(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    for jid in ("j_own_1", "j_own_2"):
        store.write_atomic(jid, {
            "job_id": jid, "status": JobStatus.RUNNING.value,
            "instance_id": app_main.instance_state.instance_id,
            "datasets": [], "models": [], "config_path": "/x", "work_dir": "/y",
            "created_at": now_iso(), "started_at": now_iso(),
            "finished_at": None, "exit_code": None, "error_message": None,
            "pid": None, "created_by": None,
        })
    store.write_atomic("j_other", {
        "job_id": "j_other", "status": JobStatus.RUNNING.value,
        "instance_id": "OTHER-INSTANCE", "datasets": [], "models": [],
        "config_path": "/x", "work_dir": "/y", "created_at": now_iso(),
        "started_at": now_iso(), "finished_at": None, "exit_code": None,
        "error_message": None, "pid": None, "created_by": None,
    })

    res = client.get("/api/v1/jobs")
    assert res.status_code == 200
    body = res.json()
    ids = {it["job_id"] for it in body["items"]}
    assert "j_own_1" in ids and "j_own_2" in ids
    assert "j_other" not in ids
    assert body["total"] == 2


def test_get_jobs_all_true_includes_other_instances(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    store.write_atomic("j_o", {
        "job_id": "j_o", "status": JobStatus.RUNNING.value,
        "instance_id": "OTHER", "datasets": [], "models": [],
        "config_path": "/x", "work_dir": "/y", "created_at": now_iso(),
        "started_at": now_iso(), "finished_at": None, "exit_code": None,
        "error_message": None, "pid": None, "created_by": None,
    })

    res = client.get("/api/v1/jobs?all=true")
    body = res.json()
    assert "j_o" in {it["job_id"] for it in body["items"]}


def test_get_jobs_filter_by_status_and_model_path(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    mine = app_main.instance_state.instance_id
    for jid, st, mp in [
        ("j1", "running", "qwen"),
        ("j2", "completed", "qwen"),
        ("j3", "running", "gpt"),
    ]:
        store.write_atomic(jid, {
            "job_id": jid, "status": st, "instance_id": mine,
            "datasets": [], "models": [{"type": "x", "path": mp}],
            "config_path": "/x", "work_dir": "/y", "created_at": now_iso(),
            "started_at": now_iso(), "finished_at": None, "exit_code": None,
            "error_message": None, "pid": None, "created_by": None,
        })
    r1 = client.get("/api/v1/jobs?status=running")
    assert {it["job_id"] for it in r1.json()["items"]} == {"j1", "j3"}
    r2 = client.get("/api/v1/jobs?model_path=qwen")
    assert {it["job_id"] for it in r2.json()["items"]} == {"j1", "j2"}


def test_get_jobs_pagination(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    mine = app_main.instance_state.instance_id
    for i in range(5):
        store.write_atomic(f"page_{i}", {
            "job_id": f"page_{i}", "status": JobStatus.RUNNING.value,
            "instance_id": mine, "datasets": [], "models": [],
            "config_path": "/x", "work_dir": "/y", "created_at": now_iso(),
            "started_at": now_iso(), "finished_at": None, "exit_code": None,
            "error_message": None, "pid": None, "created_by": None,
        })
    r1 = client.get("/api/v1/jobs?limit=2&offset=0")
    assert r1.json()["total"] == 5
    assert len(r1.json()["items"]) == 2
    r2 = client.get("/api/v1/jobs?limit=2&offset=2")
    assert len(r2.json()["items"]) == 2
    r3 = client.get("/api/v1/jobs?limit=2&offset=4")
    assert len(r3.json()["items"]) == 1
