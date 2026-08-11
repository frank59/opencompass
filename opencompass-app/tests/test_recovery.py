"""单元测试 app.utils.recovery。"""
import asyncio
import os

import pytest

from app.core.state import InstanceState
from app.utils.recovery import (
    is_pid_in_current_session,
    recover_after_restart,
)


def test_is_pid_returns_true_for_self():
    """当前进程 PID 必然存活。"""
    assert is_pid_in_current_session(os.getpid()) is True


def test_is_pid_returns_false_for_missing():
    """PID 999999 几乎肯定不存在。"""
    assert is_pid_in_current_session(999999) is False


def test_is_pid_returns_false_for_none():
    assert is_pid_in_current_session(None) is False


# ---------------------------------------------------------------------------
# recover_after_restart state-branch coverage (Phase 3 / Task 3)
# ---------------------------------------------------------------------------


@pytest.fixture
def inst():
    return InstanceState(max_concurrent=4, instance_id="test-inst")


@pytest.fixture
def store(tmp_path):
    from app.stores.nfs_state import JobStateStore
    s = JobStateStore(base_dir=str(tmp_path))
    return s


def _seed_running(store, instance_id, job_id, status="running", pid=None):
    state = {
        "job_id": job_id,
        "status": status,
        "instance_id": instance_id,
        "pid": pid,
        "datasets": [],
        "models": [],
        "config_path": "/x",
        "work_dir": "/y",
        "created_at": "2026-08-11T00:00:00Z",
    }
    store.write_atomic(job_id, state)


def test_recover_no_state_files_is_noop(store, inst):
    asyncio.run(recover_after_restart(store, inst))
    assert store.list_all() == []


def test_recover_skips_other_instances(store, inst):
    _seed_running(store, "OTHER-INSTANCE", "j1")
    asyncio.run(recover_after_restart(store, inst))
    # 别人的任务不动
    assert store.read("j1")["status"] == "running"
    assert inst.running_count() == 0


def test_recover_starting_marks_failed(store, inst):
    _seed_running(store, inst.instance_id, "j_start", status="starting")
    asyncio.run(recover_after_restart(store, inst))
    state = store.read("j_start")
    assert state["status"] == "failed"
    assert "before subprocess started" in state["error_message"]


def test_recover_running_marks_failed_when_pid_missing(store, inst):
    _seed_running(store, inst.instance_id, "j_run", status="running", pid=999999)
    asyncio.run(recover_after_restart(store, inst))
    state = store.read("j_run")
    assert state["status"] == "failed"
    assert "PID 999999 not in current session" in state["error_message"]


def test_recover_cancelling_marks_failed_when_pid_missing(store, inst):
    _seed_running(store, inst.instance_id, "j_can", status="cancelling", pid=999999)
    asyncio.run(recover_after_restart(store, inst))
    state = store.read("j_can")
    assert state["status"] == "failed"
    assert "not in current session" in state["error_message"]


def test_recover_finalizing_marks_failed(store, inst):
    _seed_running(store, inst.instance_id, "j_fin", status="finalizing")
    asyncio.run(recover_after_restart(store, inst))
    state = store.read("j_fin")
    assert state["status"] == "failed"
    assert "during finalization" in state["error_message"]


def test_recover_terminal_states_unchanged(store, inst):
    for status in ("completed", "failed", "cancelled"):
        _seed_running(store, inst.instance_id, f"j_{status}", status=status)
    asyncio.run(recover_after_restart(store, inst))
    for status in ("completed", "failed", "cancelled"):
        assert store.read(f"j_{status}")["status"] == status


def test_recover_aligns_slot_count(store, inst):
    _seed_running(store, inst.instance_id, "j_a", status="running", pid=999999)
    asyncio.run(recover_after_restart(store, inst))
    # recover 时 reserve + release，_running 应被清空
    assert inst.running_count() == 0
