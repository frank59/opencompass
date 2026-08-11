"""集成测试：lifespan startup 跑 recover + 残留任务被标记 failed。"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tmp_oc_root(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("INSTANCE_ID", "restart-inst")
    monkeypatch.setenv("MAX_CONCURRENT", "4")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    return tmp_path


def _seed_state(base_dir, job_id, status="running", pid=999999):
    p = Path(base_dir) / "workspace" / "state" / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    state = {
        "job_id": job_id,
        "status": status,
        "instance_id": "restart-inst",
        "pid": pid,
        "datasets": [],
        "models": [],
        "config_path": "/x",
        "work_dir": "/y",
        "created_at": "2026-08-11T00:00:00Z",
    }
    (p / f"{job_id}.json").write_text(json.dumps(state))


def test_recovery_on_startup_marks_residual_failed(tmp_oc_root):
    _seed_state(tmp_oc_root, "residual_starting", status="starting", pid=None)
    _seed_state(tmp_oc_root, "residual_running", status="running", pid=999999)
    _seed_state(tmp_oc_root, "residual_finalizing", status="finalizing", pid=None)

    from app.core.settings import get_settings
    from app.main import create_app
    get_settings.cache_clear()
    app = create_app()

    with TestClient(app) as c:
        res = c.get("/api/v1/jobs/residual_starting")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "failed"
        assert "before subprocess started" in body["error_message"]

        res = c.get("/api/v1/jobs/residual_running")
        body = res.json()
        assert body["status"] == "failed"
        assert "not in current session" in body["error_message"]

        res = c.get("/api/v1/jobs/residual_finalizing")
        body = res.json()
        assert body["status"] == "failed"
        assert "during finalization" in body["error_message"]


def test_health_200_after_recovery_completes(tmp_oc_root):
    """recover 完成（lifespan 同步执行）后 /health 200。"""
    from app.core.settings import get_settings
    from app.main import create_app
    get_settings.cache_clear()
    app = create_app()

    with TestClient(app) as c:
        res = c.get("/health")
        assert res.status_code == 200


def test_recovery_skips_other_instances_state_files(tmp_oc_root):
    """别人的残留任务不动。"""
    p = tmp_oc_root / "workspace" / "state" / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    state = {
        "job_id": "other_inst_task",
        "status": "running",
        "instance_id": "OTHER-INSTANCE",
        "pid": None,
        "datasets": [],
        "models": [],
        "config_path": "/x",
        "work_dir": "/y",
        "created_at": "2026-08-11T00:00:00Z",
    }
    (p / "other_inst_task.json").write_text(json.dumps(state))

    from app.core.settings import get_settings
    from app.main import create_app
    get_settings.cache_clear()
    app = create_app()

    with TestClient(app) as c:
        body = c.get("/api/v1/jobs/other_inst_task").json()
        assert body["status"] == "running"
