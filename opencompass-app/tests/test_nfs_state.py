import json

import pytest

from app.stores.nfs_state import JobStateStore


@pytest.fixture
def store(tmp_path):
    return JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))


def test_write_atomic_creates_file(store, tmp_path):
    store.write_atomic("job_a", {"job_id": "job_a", "status": "starting"})
    p = tmp_path / "state" / "jobs" / "job_a.json"
    assert p.exists()
    assert json.loads(p.read_text())["status"] == "starting"


def test_write_atomic_overwrites(store):
    store.write_atomic("job_a", {"status": "running"})
    store.write_atomic("job_a", {"status": "completed"})
    assert store.read("job_a")["status"] == "completed"


def test_read_missing_returns_none(store):
    assert store.read("nope") is None


def test_exists(store):
    assert not store.exists("job_a")
    store.write_atomic("job_a", {"status": "x"})
    assert store.exists("job_a")


def test_list_ids_filters_tmp_files(store):
    store.write_atomic("job_a", {"x": 1})
    store.write_atomic("job_b", {"x": 2})
    # 模拟残留 tmp 文件
    (store.base_dir / ".job_c.tmp").write_text("partial")
    ids = store.list_ids()
    assert sorted(ids) == ["job_a", "job_b"]


def test_write_atomic_cleans_tmp_on_failure(store, monkeypatch):
    """os.replace 抛错时，临时文件必须被清理。"""
    from app.stores import nfs_state as mod

    real_replace = mod.os.replace

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store.write_atomic("job_x", {"x": 1})
    # 临时文件应被删除
    leftovers = [p for p in store.base_dir.iterdir() if p.name.startswith(".job_x")]
    assert leftovers == []
    # 目标文件也不应存在
    assert not store.exists("job_x")
    monkeypatch.setattr(mod.os, "replace", real_replace)  # 还原
