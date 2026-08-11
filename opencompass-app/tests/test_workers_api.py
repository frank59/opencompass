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


def test_health_503_when_not_ready(client):
    from app import main as app_main
    app_main.instance_state.ready = False
    res = client.get("/health")
    assert res.status_code == 503


def test_health_200_after_ready(client):
    from app import main as app_main
    app_main.instance_state.ready = True
    res = client.get("/health")
    assert res.status_code == 200


def test_patch_capacity_success_updates_state(client):
    res = client.patch(
        "/api/v1/workers/me/capacity",
        json={"max_concurrent": 16},
    )
    assert res.status_code == 200
    assert res.json() == {"max_concurrent": 16}
    from app import main as app_main
    assert app_main.instance_state.max_concurrent == 16


def test_patch_capacity_below_running_returns_409(client):
    from app import main as app_main
    asyncio.run(app_main.instance_state.try_acquire("job_a"))
    asyncio.run(app_main.instance_state.try_acquire("job_b"))
    res = client.patch(
        "/api/v1/workers/me/capacity",
        json={"max_concurrent": 1},
    )
    assert res.status_code == 409
    assert "less than current running" in res.json()["detail"]


def test_patch_capacity_zero_returns_422(client):
    res = client.patch(
        "/api/v1/workers/me/capacity",
        json={"max_concurrent": 0},
    )
    assert res.status_code == 422


def test_patch_capacity_negative_returns_422(client):
    res = client.patch(
        "/api/v1/workers/me/capacity",
        json={"max_concurrent": -1},
    )
    assert res.status_code == 422


def test_patch_capacity_missing_field_returns_422(client):
    res = client.patch(
        "/api/v1/workers/me/capacity",
        json={},
    )
    assert res.status_code == 422


def test_patch_capacity_503_when_not_ready(client):
    from app import main as app_main
    app_main.instance_state.ready = False
    res = client.patch(
        "/api/v1/workers/me/capacity",
        json={"max_concurrent": 8},
    )
    assert res.status_code == 503
