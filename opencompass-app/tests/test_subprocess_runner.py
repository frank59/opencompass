import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.core.state import InstanceState
from app.executor.subprocess_runner import request_cancel, start, wait_and_finalize
from app.stores.nfs_state import JobStateStore


def test_start_constructs_correct_command(monkeypatch, tmp_path):
    captured = {}

    class FakeProc:
        pid = 12345

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    config_path = (
        tmp_path
        / "workspace"
        / "_in_progress"
        / "job_x"
        / "run_001"
        / "configs"
        / "job_x.py"
    )
    config_path.parent.mkdir(parents=True)
    config_path.write_text("# empty\n", encoding="utf-8")

    proc = asyncio.run(start("job_x", str(config_path)))
    cmd = captured["cmd"]
    assert cmd[0] == "opencompass"
    assert cmd[1] == str(config_path)
    assert cmd[2] == "-w"
    assert cmd[3] == str(tmp_path / "workspace" / "_in_progress" / "job_x")
    assert cmd[4] == "-r"
    assert cmd[5] == "run_001"
    assert proc.pid == 12345


def test_wait_and_finalize_marks_completed_on_zero(tmp_path):
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_z", {
        "job_id": "job_z",
        "status": "running",
        "instance_id": "i",
        "datasets": [],
        "models": [],
        "config_path": "/x",
        "work_dir": "/y",
        "created_at": "t",
        "started_at": "t",
        "finished_at": None,
        "exit_code": None,
        "error_message": None,
        "pid": 1,
        "created_by": None,
    })

    proc = MagicMock()
    proc.wait = AsyncMock(return_value=0)

    instance = InstanceState(max_concurrent=4, instance_id="test-inst")
    asyncio.run(instance.try_acquire("job_z"))

    asyncio.run(wait_and_finalize("job_z", proc, store, instance))

    final = store.read("job_z")
    assert final["status"] == "completed"
    assert final["exit_code"] == 0
    assert final["finished_at"] is not None
    assert instance.running_count() == 0


def test_wait_and_finalize_marks_failed_on_nonzero(tmp_path):
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_y", {"job_id": "job_y", "status": "running"})
    proc = MagicMock()
    proc.wait = AsyncMock(return_value=2)
    instance = InstanceState(max_concurrent=4, instance_id="test-inst")
    asyncio.run(instance.try_acquire("job_y"))

    asyncio.run(wait_and_finalize("job_y", proc, store, instance))

    final = store.read("job_y")
    assert final["status"] == "failed"
    assert final["exit_code"] == 2
    assert "opencompass exit 2" in final["error_message"]
    assert instance.running_count() == 0


def test_wait_and_finalize_no_op_when_state_missing(tmp_path):
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    proc = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    instance = InstanceState(max_concurrent=4, instance_id="test-inst")
    asyncio.run(instance.try_acquire("job_gone"))
    # 不抛错即可
    asyncio.run(wait_and_finalize("job_gone", proc, store, instance))


def test_request_cancel_returns_when_proc_already_exited():
    proc = MagicMock()
    proc.returncode = 0
    proc.terminate = MagicMock()
    asyncio.run(request_cancel(proc))
    proc.terminate.assert_not_called()


def test_request_cancel_terminates_then_awaits_wait():
    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    asyncio.run(request_cancel(proc, grace_seconds=1))
    proc.terminate.assert_called_once()
    proc.wait.assert_awaited()


def test_request_cancel_kills_after_timeout():
    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    # wait 持续超时 → wait_for 触发 SIGKILL
    proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
    asyncio.run(request_cancel(proc, grace_seconds=0))
    proc.kill.assert_called_once()
