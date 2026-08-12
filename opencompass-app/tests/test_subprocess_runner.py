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
    # 默认行为（log_path=None）：stdout=PIPE，stderr=STDOUT
    assert captured["kwargs"]["stdout"] == asyncio.subprocess.PIPE
    assert captured["kwargs"]["stderr"] == asyncio.subprocess.STDOUT


def test_start_with_log_path_opens_unbuffered_and_keeps_handle(monkeypatch, tmp_path):
    """Phase 4: log_path 给出时 stdout 写入文件，保留 fp 引用防 SIGPIPE。"""
    captured = {}

    class FakeProc:
        pid = 54321

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

    log_path = (
        tmp_path
        / "workspace"
        / "_in_progress"
        / "job_x"
        / "run_001"
        / "logs"
        / "opencompass.log"
    )
    assert not log_path.exists()  # start() 应创建父目录

    proc = asyncio.run(start("job_x", str(config_path), log_path))

    # 验证 stdout 是打开的文件（不是 PIPE）
    stdout = captured["kwargs"]["stdout"]
    assert hasattr(stdout, "write"), "stdout should be an open file, not PIPE"
    assert stdout.mode == "wb"
    # buffering=0 让子进程 write() 立即落盘 — 返回类型是 _io.FileIO（无 buffer 层）
    assert type(stdout).__name__ == "FileIO", f"expected FileIO, got {type(stdout).__name__}"
    assert captured["kwargs"]["stderr"] == asyncio.subprocess.STDOUT

    # 关键：fp 引用挂在 proc._log_fp，否则 Python GC 会关 fd
    assert hasattr(proc, "_log_fp")
    assert proc._log_fp is stdout

    # log_path 父目录应已被创建
    assert log_path.parent.exists()
    stdout.close()


def test_start_without_log_path_uses_pipe(monkeypatch, tmp_path):
    """不传 log_path 时保持旧 PIPE 行为（兼容旧单测）。"""
    captured = {}

    class FakeProc:
        pid = 9999

    async def fake_exec(*cmd, **kwargs):
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    config_path = tmp_path / "job.py"
    config_path.write_text("# x\n", encoding="utf-8")

    asyncio.run(start("j", str(config_path)))
    assert captured["kwargs"]["stdout"] == asyncio.subprocess.PIPE


def test_wait_and_finalize_closes_log_fp(tmp_path):
    """Phase 4: wait_and_finalize 后关闭挂在 proc 上的 _log_fp。"""
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_log", {"job_id": "job_log", "status": "running"})

    log_fp = open(tmp_path / "log.txt", "wb", buffering=0)
    proc = MagicMock()
    proc.pid = 1
    proc.wait = AsyncMock(return_value=0)
    proc._log_fp = log_fp

    instance = InstanceState(max_concurrent=4, instance_id="i")
    asyncio.run(instance.try_acquire("job_log"))
    asyncio.run(wait_and_finalize("job_log", proc, store, instance))

    assert log_fp.closed, "log_fp should be closed after wait_and_finalize"
    assert not hasattr(proc, "_log_fp"), "_log_fp attr should be deleted"


def test_wait_and_finalize_no_log_fp_is_safe(tmp_path):
    """Phase 4: proc 无 _log_fp 时 wait_and_finalize 不报错。"""
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_nolog", {"job_id": "job_nolog", "status": "running"})

    proc = MagicMock()
    proc.pid = 2
    proc.wait = AsyncMock(return_value=0)
    # 不设 _log_fp

    instance = InstanceState(max_concurrent=4, instance_id="i")
    asyncio.run(instance.try_acquire("job_nolog"))
    # 不应抛 AttributeError
    asyncio.run(wait_and_finalize("job_nolog", proc, store, instance))


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


def test_wait_and_finalize_marks_cancelled_when_state_is_cancelling(tmp_path):
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_c", {"job_id": "job_c", "status": "cancelling"})
    proc = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    instance = InstanceState(max_concurrent=4, instance_id="test-inst")
    asyncio.run(instance.try_acquire("job_c"))

    asyncio.run(wait_and_finalize("job_c", proc, store, instance))

    final = store.read("job_c")
    assert final["status"] == "cancelled"
    assert final["error_message"] == "cancelled by user"
    assert instance.running_count() == 0


def test_wait_and_finalize_keeps_completed_path_for_normal_exit(tmp_path):
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_d", {"job_id": "job_d", "status": "running"})
    proc = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    instance = InstanceState(max_concurrent=4, instance_id="test-inst")
    asyncio.run(instance.try_acquire("job_d"))

    asyncio.run(wait_and_finalize("job_d", proc, store, instance))

    final = store.read("job_d")
    assert final["status"] == "completed"
    assert final["error_message"] is None


def test_cancel_then_finalize_writes_cancelled(tmp_path):
    """集成：request_cancel 发信号 → wait_and_finalize 收尾 → CANCELLED。"""
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_e", {"job_id": "job_e", "status": "cancelling"})

    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(return_value=0)

    instance = InstanceState(max_concurrent=4, instance_id="test-inst")
    asyncio.run(instance.try_acquire("job_e"))

    asyncio.run(request_cancel(proc, grace_seconds=1))
    asyncio.run(wait_and_finalize("job_e", proc, store, instance))

    final = store.read("job_e")
    assert final["status"] == "cancelled"
    assert final["error_message"] == "cancelled by user"
    assert instance.running_count() == 0


def test_finalize_after_kill_keeps_cancelled(tmp_path):
    """集成：request_cancel 走到 SIGKILL → wait_and_finalize 仍写 CANCELLED。"""
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_f", {"job_id": "job_f", "status": "cancelling"})

    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    # wait_for 阶段抛 TimeoutError → SIGKILL；kill 后 best-effort wait 忽略异常
    proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())

    instance = InstanceState(max_concurrent=4, instance_id="test-inst")
    asyncio.run(instance.try_acquire("job_f"))

    asyncio.run(request_cancel(proc, grace_seconds=0))
    # 模拟进程在 SIGKILL 后以 exit code 137 退出
    proc.wait = AsyncMock(return_value=137)
    asyncio.run(wait_and_finalize("job_f", proc, store, instance))

    final = store.read("job_f")
    assert final["status"] == "cancelled"
    assert final["exit_code"] == 137
