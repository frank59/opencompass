import asyncio

from app import main as app_main


def test_health_ok_when_state_writable(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in ("healthy", "degraded")
    assert "nfs_state" in body["checks"]
    assert "opencompass_binary" in body["checks"]


def test_workers_me_free_returns_counts(client):
    res = client.get("/api/v1/workers/me/free")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] == body["max"] - body["running"]
    assert body["max"] == app_main.instance_state.max_concurrent


def test_workers_me_free_after_acquire(client):
    asyncio.run(app_main.instance_state.try_acquire("job_a"))
    res = client.get("/api/v1/workers/me/free")
    body = res.json()
    assert body["running"] == 1
    assert body["available"] == body["max"] - 1


def test_health_degraded_when_nfs_state_fails(client, monkeypatch):
    def boom():
        raise OSError("disk gone")
    monkeypatch.setattr(app_main.state_store, "list_ids", boom)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "degraded"
    assert body["checks"]["nfs_state"].startswith("fail")
