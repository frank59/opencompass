"""Phase 2 端到端：创建 → 列出 → 停止 → 收尾 → 删除。"""

import pytest
from fastapi.testclient import TestClient

from app.core.dataset_registry import DatasetRegistry
from app.core.dataset_whitelist import DatasetWhitelist
from app.core.model_whitelist import ModelWhitelist
from app.main import create_app
from app.models.enums import JobStatus


@pytest.fixture
def e2e_client(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "di.yaml"
    fake_yaml.write_text(
        "- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n",
        encoding="utf-8",
    )
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

    # fake_start 让 wait 永远不返回 → 状态保持 running，便于后续 stop 测试
    from unittest.mock import MagicMock

    import app.executor.subprocess_runner as sr

    async def fake_start(job_id, config_path, log_path=None):
        proc = MagicMock()
        proc.pid = 99999

        async def wait_forever():
            await pytest.importorskip("asyncio").Event().wait()

        proc.wait = wait_forever
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        return proc

    async def fake_wait_and_finalize(*args, **kwargs):
        # 模拟 client stop 后，状态由 client 写到 CANCELLING
        # 再由 finalize 写到 CANCELLED（这里直接交给 client 测试场景处理）
        pass

    monkeypatch.setattr(sr, "start", fake_start)
    monkeypatch.setattr(sr, "wait_and_finalize", fake_wait_and_finalize)

    app = create_app()
    with TestClient(app) as c:
        yield c

    DatasetRegistry._INDEX = None


def test_create_list_stop_delete_lifecycle(e2e_client):
    """Phase 2 端到端：POST → GET list → POST /stop → 手动 finalize → DELETE。"""
    req = {
        "job_id": "e2e_001",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{
            "type": "opencompass.models.openai_api.OpenAISDK",
            "path": "qwen", "key": "sk-test",
        }],
    }

    # 1. create
    r = e2e_client.post("/api/v1/jobs", json=req)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == JobStatus.RUNNING.value

    # 2. list
    r = e2e_client.get("/api/v1/jobs")
    assert r.status_code == 200
    items = r.json()["items"]
    e2e = [it for it in items if it["job_id"] == "e2e_001"]
    assert len(e2e) == 1
    assert e2e[0]["status"] == JobStatus.RUNNING.value

    # 3. stop
    r = e2e_client.post("/api/v1/jobs/e2e_001/stop")
    assert r.status_code == 202
    assert r.json()["status"] == JobStatus.CANCELLING.value

    # 4. 手动 simulate finalize → CANCELLED
    from app import main as app_main
    store = app_main.state_store
    current = store.read("e2e_001")
    assert current["status"] == JobStatus.CANCELLING.value
    store.write_atomic("e2e_001", {
        **current,
        "status": JobStatus.CANCELLED.value,
        "finished_at": current.get("started_at"),
        "error_message": "cancelled by user",
    })

    # 5. 复查 - 终态
    r = e2e_client.get("/api/v1/jobs/e2e_001")
    assert r.status_code == 200
    assert r.json()["status"] == JobStatus.CANCELLED.value

    # 6. delete 终态
    r = e2e_client.delete("/api/v1/jobs/e2e_001")
    assert r.status_code == 204

    # 7. 复查 - 404
    r = e2e_client.get("/api/v1/jobs/e2e_001")
    assert r.status_code == 404


def test_stop_already_cancelled_returns_409(e2e_client):
    """已 cancel 的 job 不能再 stop。"""
    from app import main as app_main
    from app.utils.time import now_iso

    store = app_main.state_store
    store.write_atomic("e2e_002", {
        "job_id": "e2e_002", "status": JobStatus.CANCELLED.value,
        "instance_id": app_main.instance_state.instance_id,
        "datasets": [], "models": [], "config_path": "/x", "work_dir": "/y",
        "created_at": now_iso(), "started_at": now_iso(),
        "finished_at": now_iso(), "exit_code": None,
        "error_message": "cancelled by user",
        "pid": None, "created_by": None,
    })

    r = e2e_client.post("/api/v1/jobs/e2e_002/stop")
    assert r.status_code == 409