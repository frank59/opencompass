# opencompass-app Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 MVP 闭环基础上扩展 3 个能力：任务停止（POST /stop）、任务列表（GET /jobs）、任务删除（DELETE /jobs/{id}）；并扩展 JobStatus 状态机支持 CANCELLING/CANCELLED。

**Architecture:** 复用 MVP 等待终态化路径，新增 request_cancel 异步发 SIGTERM/CASKILL；状态机扩展在 wait_and_finalize 增加分支；POST /stop 用 CAS 防止并发；GET /jobs 走 list_all + Python 过滤；DELETE 限定终态。

**Tech Stack:** FastAPI + Pydantic v2 + asyncio + pytest-asyncio（mode=auto） + httpx TestClient + ruff。

**Base:** MVP v1.0 已完成（22 tasks / 74 tests），位于 `develop` 分支，ahead of origin/develop 26 commits。

**Spec:** [`docs/superpowers/specs/2026-08-09-opencompass-app-phase2-design.md`](../../specs/2026-08-09-opencompass-app-phase2-design.md)

---

## 项目结构（Phase 2 变更）

```
opencompass-app/
├── app/
│   ├── models/
│   │   ├── enums.py                       # 改：+CANCELLING/+CANCELLED
│   │   └── response.py                    # 改：+cancelled_by / +JobListResponse
│   ├── api/
│   │   └── jobs.py                        # 改：+POST /stop / GET /jobs / DELETE
│   ├── stores/
│   │   └── nfs_state.py                   # 改：+list_all / +compare_and_swap
│   └── executor/
│       └── subprocess_runner.py           # 改：+request_cancel / wait_and_finalize 加分支
└── tests/
    ├── test_enums.py                      # 改
    ├── test_subprocess_runner.py          # 改
    ├── test_nfs_state.py                  # 改
    ├── test_jobs_api.py                   # 改
    └── test_jobs_phase2_e2e.py            # 新
```

## 关键决策（diff 自 MVP）

| 点 | MVP | Phase 2 新增 |
|----|-----|--------------|
| 状态值 | 5 个 | 7 个（+CANCELLING +CANCELLED） |
| 终止信号 | — | SIGTERM + 30s grace + SIGKILL |
| Stop 权限 | — | 严格 instance_id（403） |
| 列表 | — | offset+limit 分页 + 3 维过滤 |
| 删除 | — | 仅终态（completed/failed/cancelled） |

---

## 阶段 1：数据层

### Task 1.1：JobStatus 扩展 + JobResponse.cancelled_by + 测试

**Files:**
- Modify: `opencompass-app/app/models/enums.py`
- Modify: `opencompass-app/app/models/response.py`
- Modify: `opencompass-app/tests/test_enums.py`

- [ ] **Step 1：修改 `app/models/enums.py`**

```python
from enum import Enum


class JobStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
```

- [ ] **Step 2：修改 `app/models/response.py` 加 `cancelled_by` 与 `JobListResponse`**

在 `JobResponse` 末尾追加：
```python
    cancelled_by: str | None = None
```

在文件末尾追加：
```python
class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
```

- [ ] **Step 3：修改 `tests/test_enums.py` 加 2 个新状态值测试**

现有 `test_job_status_values` 改为：
```python
def test_job_status_values():
    expected = {
        "starting", "running", "finalizing", "completed", "failed",
        "cancelling", "cancelled",
    }
    actual = {s.value for s in JobStatus}
    assert actual == expected
```

追加：
```python
def test_cancelling_and_cancelled_are_str():
    assert JobStatus.CANCELLING == "cancelling"
    assert JobStatus.CANCELLED == "cancelled"
    assert isinstance(JobStatus.CANCELLING, str)
```

- [ ] **Step 4：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_enums.py -v
```

预期：3 passed（含原有 2 + 新 1）。

- [ ] **Step 5：Commit**

```bash
git add opencompass-app/app/models/enums.py opencompass-app/app/models/response.py opencompass-app/tests/test_enums.py
git commit -m "feat(models): extend JobStatus with CANCELLING/CANCELLED + cancelled_by"
```

---

### Task 1.2：JobStateStore.list_all() + 跳过 tmp

**Files:**
- Modify: `opencompass-app/app/stores/nfs_state.py`
- Modify: `opencompass-app/tests/test_nfs_state.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_nfs_state.py` 末尾追加：
```python
def test_list_all_returns_all_jobs(tmp_path):
    from app.stores.nfs_state import JobStateStore
    store = JobStateStore(base_dir=str(tmp_path / "state"))
    store.write_atomic("job_a", {"job_id": "job_a", "status": "running"})
    store.write_atomic("job_b", {"job_id": "job_b", "status": "completed"})
    items = store.list_all()
    assert {job_id for job_id, _ in items} == {"job_a", "job_b"}


def test_list_all_skips_tmp_files(tmp_path):
    from app.stores.nfs_state import JobStateStore
    store = JobStateStore(base_dir=str(tmp_path / "state"))
    store.write_atomic("job_real", {"job_id": "job_real", "status": "running"})
    (tmp_path / "state" / ".job_partial.tmp").write_text('{"incomplete":', encoding="utf-8")
    items = store.list_all()
    assert {job_id for job_id, _ in items} == {"job_real"}
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_nfs_state.py -v
```

预期：AttributeError `'JobStateStore' object has no attribute 'list_all'`。

- [ ] **Step 3：在 `app/stores/nfs_state.py` 添加 `list_all`**

现有 `list_ids` 之后追加：
```python
    def list_all(self) -> list[tuple[str, dict]]:
        """返回 (job_id, state) 列表；跳过 .tmp 失败文件。"""
        out: list[tuple[str, dict]] = []
        for p in sorted(self.base_dir.glob("*.json")):
            if not p.name.endswith(".json"):
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                out.append((data["job_id"], data))
            except (json.JSONDecodeError, KeyError, OSError):
                log.warning("skip unreadable state file: %s", p)
                continue
        return out
```

并在文件顶部 `import logging` 后追加：
```python
log = logging.getLogger(__name__)
```

- [ ] **Step 4：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_nfs_state.py -v
```

预期：8 passed（原有 6 + 新 2）。

- [ ] **Step 5：Commit**

```bash
git add opencompass-app/app/stores/nfs_state.py opencompass-app/tests/test_nfs_state.py
git commit -m "feat(stores): add list_all() to JobStateStore with tmp filter"
```

---

### Task 1.3：JobStateStore.compare_and_swap() + 状态机迁移表

**Files:**
- Modify: `opencompass-app/app/stores/nfs_state.py`
- Create: `opencompass-app/app/core/job_state_machine.py`
- Modify: `opencompass-app/tests/test_nfs_state.py`
- Create: `opencompass-app/tests/test_job_state_machine.py`

- [ ] **Step 1：创建 `app/core/job_state_machine.py` 状态机工具**

```python
"""JobStatus 状态机迁移表。

集中所有 'from → to' 合法迁移，便于 (a) 校验状态变更 (b) 文档化。
"""
from app.models.enums import JobStatus


# 起始态：STARTING / RUNNING
STARTING_OR_RUNNING = {JobStatus.STARTING.value, JobStatus.RUNNING.value}

# 终态：COMPLETED / FAILED / CANCELLED
TERMINAL = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}


def can_stop(status: str) -> bool:
    """POST /stop 接受的状态：STARTING / RUNNING。"""
    return status in STARTING_OR_RUNNING


def can_delete(status: str) -> bool:
    """DELETE 接受的状态：终态。"""
    return status in TERMINAL
```

- [ ] **Step 2：写 `test_job_state_machine.py` 测试**

```python
from app.core.job_state_machine import can_delete, can_stop
from app.models.enums import JobStatus


def test_can_stop_accepts_starting_running():
    assert can_stop(JobStatus.STARTING.value) is True
    assert can_stop(JobStatus.RUNNING.value) is True


def test_can_stop_rejects_others():
    for s in (JobStatus.FINALIZING, JobStatus.COMPLETED, JobStatus.FAILED,
              JobStatus.CANCELLING, JobStatus.CANCELLED):
        assert can_stop(s.value) is False, s


def test_can_delete_accepts_terminal():
    for s in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        assert can_delete(s.value) is True, s


def test_can_delete_rejects_non_terminal():
    for s in (JobStatus.STARTING, JobStatus.RUNNING, JobStatus.FINALIZING,
              JobStatus.CANCELLING):
        assert can_delete(s.value) is False, s
```

- [ ] **Step 3：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_job_state_machine.py -v
```

预期：4 passed。

- [ ] **Step 4：写 `test_nfs_state.py` CAS 测试**

追加：
```python
def test_compare_and_swap_succeeds_when_status_matches(tmp_path):
    from app.stores.nfs_state import JobStateStore
    store = JobStateStore(base_dir=str(tmp_path / "state"))
    store.write_atomic("job_x", {"job_id": "job_x", "status": "running"})
    result = store.compare_and_swap(
        "job_x", expected_status="running", mutation={"status": "cancelling"},
    )
    assert result is True
    assert store.read("job_x")["status"] == "cancelling"


def test_compare_and_swap_fails_when_status_mismatch(tmp_path):
    from app.stores.nfs_state import JobStateStore
    store = JobStateStore(base_dir=str(tmp_path / "state"))
    store.write_atomic("job_y", {"job_id": "job_y", "status": "completed"})
    result = store.compare_and_swap(
        "job_y", expected_status="running", mutation={"status": "cancelling"},
    )
    assert result is False
    assert store.read("job_y")["status"] == "completed"


def test_compare_and_swap_missing_returns_false(tmp_path):
    from app.stores.nfs_state import JobStateStore
    store = JobStateStore(base_dir=str(tmp_path / "state"))
    result = store.compare_and_swap(
        "job_missing", expected_status="running", mutation={"status": "cancelling"},
    )
    assert result is False
```

- [ ] **Step 5：在 `app/stores/nfs_state.py` 添加 `compare_and_swap`**

在 `list_all` 之后追加：
```python
    def compare_and_swap(
        self, job_id: str, expected_status: str, mutation: dict,
    ) -> bool:
        """CAS 写：当前状态 == expected_status 才应用 mutation。返回是否成功。"""
        current = self.read(job_id)
        if current is None:
            return False
        if current.get("status") != expected_status:
            return False
        self.write_atomic(job_id, {**current, **mutation})
        return True
```

- [ ] **Step 6：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_nfs_state.py tests/test_job_state_machine.py -v
```

预期：11 passed（nfs_state 9 + state_machine 4 - 已有 atomic write 测试 6 + 3 新 + 4 新 = 实际是 8+3+4=15）。

- [ ] **Step 7：Commit**

```bash
git add opencompass-app/app/stores/nfs_state.py opencompass-app/app/core/job_state_machine.py opencompass-app/tests/test_nfs_state.py opencompass-app/tests/test_job_state_machine.py
git commit -m "feat(stores,core): add compare_and_swap and state-machine helpers"
```

---

## 阶段 2：核心引擎

### Task 2.1：`subprocess_runner.request_cancel()` + 3 测试

**Files:**
- Modify: `opencompass-app/app/executor/subprocess_runner.py`
- Modify: `opencompass-app/tests/test_subprocess_runner.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_subprocess_runner.py` 末尾追加：
```python
def test_request_cancel_returns_when_proc_already_exited():
    from app.executor.subprocess_runner import request_cancel
    proc = MagicMock()
    proc.returncode = 0
    proc.terminate = MagicMock()
    asyncio.run(request_cancel(proc))
    proc.terminate.assert_not_called()


def test_request_cancel_terminates_then_awaits_wait():
    from app.executor.subprocess_runner import request_cancel
    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    asyncio.run(request_cancel(proc, grace_seconds=1))
    proc.terminate.assert_called_once()
    proc.wait.assert_awaited()


def test_request_cancel_kills_after_timeout():
    from app.executor.subprocess_runner import request_cancel
    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), 0])
    proc.kill = MagicMock()
    asyncio.run(request_cancel(proc, grace_seconds=0))
    proc.kill.assert_called_once()
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_subprocess_runner.py -v
```

预期：ImportError `cannot import name 'request_cancel' from 'app.executor.subprocess_runner'`。

- [ ] **Step 3：在 `app/executor/subprocess_runner.py` 添加 `request_cancel`**

```python
async def request_cancel(proc, grace_seconds: int = 30) -> None:
    """SIGTERM → 异步等 grace → SIGKILL。best-effort 强制结束。"""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
```

- [ ] **Step 4：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_subprocess_runner.py -v
```

预期：7 passed（4 旧 + 3 新）。

- [ ] **Step 5：Commit**

```bash
git add opencompass-app/app/executor/subprocess_runner.py opencompass-app/tests/test_subprocess_runner.py
git commit -m "feat(executor): add request_cancel with SIGTERM/grace/SIGKILL"
```

---

### Task 2.2：`wait_and_finalize` cancel 路径分支 + 2 测试

**Files:**
- Modify: `opencompass-app/app/executor/subprocess_runner.py`
- Modify: `opencompass-app/tests/test_subprocess_runner.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_subprocess_runner.py` 末尾追加：
```python
def test_wait_and_finalize_marks_cancelled_when_state_is_cancelling(tmp_path):
    from app.executor.subprocess_runner import wait_and_finalize
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
    from app.executor.subprocess_runner import wait_and_finalize
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
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_subprocess_runner.py::test_wait_and_finalize_marks_cancelled_when_state_is_cancelling -v
```

预期：失败 - 当前 wait_and_finalize 把状态写为 "completed"。

- [ ] **Step 3：修改 `app/executor/subprocess_runner.py` 的 `wait_and_finalize`**

替换现有 `wait_and_finalize` 函数体：
```python
async def wait_and_finalize(
    job_id: str,
    proc: asyncio.subprocess.Process,
    state_store: JobStateStore,
    instance_state: "InstanceState",
) -> None:
    """等待进程退出，把状态收敛到 completed/failed/cancelled，最后释放 worker 槽。"""
    rc = await proc.wait()
    current = state_store.read(job_id)
    if current is None:
        await instance_state.release(job_id)
        return

    if current.get("status") == JobStatus.CANCELLING.value:
        final_status = JobStatus.CANCELLED.value
        err = "cancelled by user"
    elif rc == 0:
        final_status = JobStatus.COMPLETED.value
        err = None
    else:
        final_status = JobStatus.FAILED.value
        err = f"opencompass exit {rc}"

    state_store.write_atomic(job_id, {
        **current,
        "status": final_status,
        "finished_at": now_iso(),
        "exit_code": rc,
        "error_message": err,
    })
    await instance_state.release(job_id)
```

并在文件顶部 import 后追加：
```python
from app.models.enums import JobStatus
```

- [ ] **Step 4：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_subprocess_runner.py -v
```

预期：9 passed（7 旧 + 2 新）。

- [ ] **Step 5：Commit**

```bash
git add opencompass-app/app/executor/subprocess_runner.py opencompass-app/tests/test_subprocess_runner.py
git commit -m "feat(executor): wait_and_finalize branches to CANCELLED when state was cancelling"
```

---

### Task 2.3：subprocess_runner 集成测试 - 取消流程端到端

**Files:**
- Modify: `opencompass-app/tests/test_subprocess_runner.py`

- [ ] **Step 1：写集成测试**

在 `tests/test_subprocess_runner.py` 末尾追加：
```python
def test_cancel_then_finalize_writes_cancelled(tmp_path):
    """集成：request_cancel 发信号 → wait_and_finalize 收尾 → CANCELLED。"""
    from app.executor.subprocess_runner import request_cancel, wait_and_finalize
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic(
        "job_e",
        {"job_id": "job_e", "status": "cancelling"},
    )

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
    from app.executor.subprocess_runner import request_cancel, wait_and_finalize
    store = JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))
    store.write_atomic("job_f", {"job_id": "job_f", "status": "cancelling"})

    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    # request_cancel 阶段：wait 超时 → SIGKILL
    # wait_and_finalize 阶段：wait 立即返回 137
    wait_call_count = [0]

    async def wait_side_effect():
        wait_call_count[0] += 1
        if wait_call_count[0] == 1:
            raise asyncio.TimeoutError()
        return 137

    proc.wait = AsyncMock(side_effect=wait_side_effect)

    instance = InstanceState(max_concurrent=4, instance_id="test-inst")
    asyncio.run(instance.try_acquire("job_f"))

    asyncio.run(request_cancel(proc, grace_seconds=0))
    asyncio.run(wait_and_finalize("job_f", proc, store, instance))

    final = store.read("job_f")
    assert final["status"] == "cancelled"
    assert final["exit_code"] == 137
```

- [ ] **Step 2：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_subprocess_runner.py -v
```

预期：11 passed（9 旧 + 2 集成）。

- [ ] **Step 3：Commit**

```bash
git add opencompass-app/tests/test_subprocess_runner.py
git commit -m "test(executor): integration tests for cancel + finalize flow"
```

---

## 阶段 3：API 层

### Task 3.1：POST /api/v1/jobs/{job_id}/stop + 5 测试

**Files:**
- Modify: `opencompass-app/app/api/jobs.py`
- Modify: `opencompass-app/tests/test_jobs_api.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_jobs_api.py` 末尾追加：
```python
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
    from app.core.settings import get_settings
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
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_api.py -k "stop" -v
```

预期：404 / 405（路由不存在）。

- [ ] **Step 3：在 `app/api/jobs.py` 添加 `stop_job` 端点**

在 `_validate_request` 之后、`create_job` 之前插入 import：
```python
from app.core.job_state_machine import can_stop
```

在 `get_job` 之后追加 `stop_job` 已 import 助手：
```python
@router.post("/{job_id}/stop", status_code=202)
async def stop_job(job_id: str) -> dict:
    """任务停止：CAS 写 STARTING/RUNNING → CANCELLING，再 SIGTERM 进程。"""
    from app.main import get_instance_state, get_state_store

    store = get_state_store()
    inst = get_instance_state()

    current = store.read(job_id)
    if current is None:
        raise HTTPException(404, "job not found")

    if current.get("instance_id") != inst.instance_id:
        raise HTTPException(
            403, f"job owned by other instance: {current.get('instance_id')}"
        )

    if not can_stop(current.get("status", "")):
        raise HTTPException(
            409, f"cannot stop job in status {current.get('status')}"
        )

    ok = store.compare_and_swap(
        job_id,
        expected_status=current["status"],
        mutation={"status": "cancelling"},
    )
    if not ok:
        raise HTTPException(409, "already cancelling")

    proc = inst.get_process(job_id)
    if proc is not None:
        from app.executor import subprocess_runner
        asyncio.create_task(subprocess_runner.request_cancel(proc))

    return {"job_id": job_id, "status": "cancelling"}
```

- [ ] **Step 4：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_api.py -v
```

预期：12 passed（7 旧 + 5 新）。

- [ ] **Step 5：Commit**

```bash
git add opencompass-app/app/api/jobs.py opencompass-app/tests/test_jobs_api.py
git commit -m "feat(api): add POST /jobs/{id}/stop with CAS state transition"
```

---

### Task 3.2：GET /api/v1/jobs 列表 + 过滤 + 分页 + 4 测试

**Files:**
- Modify: `opencompass-app/app/api/jobs.py`
- Modify: `opencompass-app/tests/test_jobs_api.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_jobs_api.py` 末尾追加：
```python
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
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_api.py -k "list or filter or pagination" -v
```

预期：404 / 405（路由不存在）。

- [ ] **Step 3：在 `app/api/jobs.py` 添加 `list_jobs` 端点**

在 `stop_job` 之后追加：
```python
@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: str | None = None,
    model_path: str | None = None,
    all: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> JobListResponse:
    """列出任务：filter + offset/limit 分页。"""
    from app.main import get_instance_state, get_state_store

    store = get_state_store()
    inst = get_instance_state()

    items = store.list_all()
    filtered: list[dict] = []
    for _, state in items:
        if not all and state.get("instance_id") != inst.instance_id:
            continue
        if status is not None and state.get("status") != status:
            continue
        if model_path is not None:
            models = state.get("models") or []
            if not any(model_path in (m.get("path") or "") for m in models):
                continue
        filtered.append(state)

    filtered.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    total = len(filtered)
    page = filtered[offset:offset + limit]
    return JobListResponse(
        items=[JobResponse(**s) for s in page],
        total=total,
        limit=limit,
        offset=offset,
    )
```

- [ ] **Step 4：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_api.py -v
```

预期：16 passed（12 旧 + 4 新）。

- [ ] **Step 5：Commit**

```bash
git add opencompass-app/app/api/jobs.py opencompass-app/tests/test_jobs_api.py
git commit -m "feat(api): add GET /jobs with status/model_path/all filters and pagination"
```

---

### Task 3.3：DELETE /api/v1/jobs/{job_id} + 3 测试

**Files:**
- Modify: `opencompass-app/app/api/jobs.py`
- Modify: `opencompass-app/tests/test_jobs_api.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_jobs_api.py` 末尾追加：
```python
def test_delete_job_204_for_terminal(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    store.write_atomic("j_del", {
        "job_id": "j_del", "status": JobStatus.COMPLETED.value,
        "instance_id": app_main.instance_state.instance_id,
        "datasets": [], "models": [], "config_path": "/x", "work_dir": "/y",
        "created_at": now_iso(), "started_at": now_iso(),
        "finished_at": now_iso(), "exit_code": 0, "error_message": None,
        "pid": None, "created_by": None,
    })
    res = client.delete("/api/v1/jobs/j_del")
    assert res.status_code == 204
    assert store.read("j_del") is None


def test_delete_job_404_when_missing(client):
    res = client.delete("/api/v1/jobs/no_such_xyz")
    assert res.status_code == 404


def test_delete_job_409_when_running(client):
    from app import main as app_main
    from app.models.enums import JobStatus
    from app.utils.time import now_iso
    store = app_main.state_store
    store.write_atomic("j_running", {
        "job_id": "j_running", "status": JobStatus.RUNNING.value,
        "instance_id": app_main.instance_state.instance_id,
        "datasets": [], "models": [], "config_path": "/x", "work_dir": "/y",
        "created_at": now_iso(), "started_at": now_iso(),
        "finished_at": None, "exit_code": None, "error_message": None,
        "pid": None, "created_by": None,
    })
    res = client.delete("/api/v1/jobs/j_running")
    assert res.status_code == 409
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_api.py -k "delete" -v
```

预期：405 / 404（路由不存在）。

- [ ] **Step 3：在 `app/api/jobs.py` 添加 `delete_job` 端点**

在 `list_jobs` 之后追加：
```python
@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str) -> None:
    """删除任务：仅终态允许。"""
    from app.main import get_state_store

    store = get_state_store()
    current = store.read(job_id)
    if current is None:
        raise HTTPException(404, "job not found")
    if not can_delete(current.get("status", "")):
        raise HTTPException(
            409, f"cannot delete in status {current.get('status')}"
        )
    store.delete(job_id)
```

并新增 `delete` 方法到 `JobStateStore`：

在 `app/stores/nfs_state.py` 的 `write_atomic` 之后追加：
```python
    def delete(self, job_id: str) -> None:
        """删除任务状态文件；不存在则静默成功。"""
        target = self._path(job_id)
        try:
            target.unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Step 4：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_api.py -v
```

预期：19 passed（16 旧 + 3 新）。

- [ ] **Step 5：Commit**

```bash
git add opencompass-app/app/api/jobs.py opencompass-app/app/stores/nfs_state.py opencompass-app/tests/test_jobs_api.py
git commit -m "feat(api,stores): add DELETE /jobs/{id} (terminal only) + JobStateStore.delete"
```

---

### Task 3.4：端到端 happy path 集成测试

**Files:**
- Create: `opencompass-app/tests/test_jobs_phase2_e2e.py`

- [ ] **Step 1：写端到端测试**

```python
"""Phase 2 端到端：创建 → 停止 → 列表 → 删除。"""
from unittest.mock import AsyncMock


def test_full_lifecycle_create_stop_list_delete(client, monkeypatch):
    from app import main as app_main
    from app.models.enums import JobStatus

    # 桩掉 start()，让其很快"完成"
    import app.executor.subprocess_runner as sr
    async def fake_start(job_id, config_path):
        from unittest.mock import AsyncMock, MagicMock
        proc = MagicMock()
        proc.pid = 12345
        proc.returncode = 0
        proc.wait = AsyncMock(return_value=0)
        return proc
    monkeypatch.setattr(sr, "start", fake_start)

    # 1. create
    req = {
        "job_id": "e2e_001",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    r = client.post("/api/v1/jobs", json=req)
    assert r.status_code == 201

    # 2. wait 按 spec 走，task 收尾完成
    import time
    time.sleep(0.5)

    # 3. list - 检查任务存在（可能 running/completed/failed）
    r = client.get("/api/v1/jobs")
    assert r.status_code == 200
    body = r.json()
    e2e = [it for it in body["items"] if it["job_id"] == "e2e_001"]
    assert len(e2e) == 1

    # 4. 如果仍是非终态，stop 它
    target = e2e[0]
    if target["status"] not in (JobStatus.COMPLETED.value, JobStatus.FAILED.value,
                                 JobStatus.CANCELLED.value):
        r = client.post("/api/v1/jobs/e2e_001/stop")
        assert r.status_code == 202

    # 5. 等收尾
    time.sleep(0.5)

    # 6. 复查状态 - 应为终态
    r = client.get("/api/v1/jobs/e2e_001")
    final = r.json()
    assert final["status"] in (
        JobStatus.COMPLETED.value, JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    )

    # 7. delete 终态
    r = client.delete("/api/v1/jobs/e2e_001")
    assert r.status_code == 204

    # 8. 复查 - 404
    r = client.get("/api/v1/jobs/e2e_001")
    assert r.status_code == 404
```

- [ ] **Step 2：跑测试**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_phase2_e2e.py -v
```

预期：1 passed。

- [ ] **Step 3：Commit**

```bash
git add opencompass-app/tests/test_jobs_phase2_e2e.py
git commit -m "test(api): Phase 2 end-to-end lifecycle (create→stop→list→delete)"
```

---

## 阶段 4：联调

### Task 4.1：ruff 全量 + 完整测试套件

**Files:** (no source changes expected)

- [ ] **Step 1：ruff**

```bash
cd opencompass-app
ruff check app/ tests/
```

预期：`All checks passed!` 或仅修复少量自动可修问题。

- [ ] **Step 2：全量测试**

```bash
cd opencompass-app
python3 -m pytest tests/ -v --tb=short
```

预期：≥ 90 用例通过（74 MVP + 16 Phase 2）。

- [ ] **Step 3：黑盒集成约束**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git diff --stat opencompass/ 2>&1 | tail -3
git status opencompass/ | head -3
```

预期：`opencompass/` 仍 clean。

- [ ] **Step 4：如有 lint 修复，提交**

```bash
git add opencompass-app/
git commit -m "chore(app): Phase 2 lint fixes"
```

（如无需修复，跳过）

---

### Task 4.2：README 更新 + 完工报告

**Files:**
- Modify: `opencompass-app/README.md`

- [ ] **Step 1：在 README 新增 Phase 2 端点表**

```markdown
## Phase 2 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/jobs/{job_id}/stop` | POST | 停止任务（CAS 转 CANCELLING + SIGTERM） |
| `/api/v1/jobs` | GET | 列表 + 过滤（status / model_path / all）+ offset/limit 分页 |
| `/api/v1/jobs/{job_id}` | DELETE | 删除任务（仅终态） |
```

- [ ] **Step 2：提交**

```bash
git add opencompass-app/README.md
git commit -m "docs(app): document Phase 2 endpoints in README"
```

- [ ] **Step 3：输出完工报告**

报告应包含：
- 阶段 × 任务数 × 提交数
- 测试用例数（基线 vs 终结）
- 三个新端点的状态码矩阵
- blacklist marshal（opencompass/ 0 diff）
- 已知限制（如跨实例 stop 进程清理）

---

## 实施总结

| 阶段 | 任务 | 估算代码行（含测试） |
|------|------|---------------------|
| 1 数据层 | 3 | ~200 |
| 2 核心引擎 | 3 | ~250 |
| 3 API 层 | 4 | ~400 |
| 4 联调 | 2 | ~80 |
| **合计** | **12** | **≈930** |

## 自检结果（writing-plans self-review）

**1. Spec coverage**（spec §X → 本 plan Task Y）

- §3 JobStatus 扩展 ✅ → Task 1.1
- §3 状态迁移 ✅ → Task 1.3 + Task 2.2
- §4.2 request_cancel ✅ → Task 2.1
- §4.2 wait_and_finalize 分支 ✅ → Task 2.2
- §5.1 POST /stop ✅ → Task 3.1
- §5.2 GET /jobs ✅ → Task 3.2
- §5.3 DELETE ✅ → Task 3.3
- §5.4 GET /jobs/{id} 扩展 ✅ → Task 1.1（cancelled_by）
- §7 test 策略 ✅ → Task 1.2/1.3/2.1/2.2/3.1/3.2/3.3/3.4

**2. Placeholder scan**

无 TBD / TODO / "implement later"。

**3. Type consistency**

- `JobStatus` 7 个值在 Task 1.1 定义，Task 1.3/2.2/3.1/3.2/3.3 全部引用一致
- `JobResponse.cancelled_by` 仅 Task 1.1 定义，Task 3.2 通过 `JobResponse(**s)` 隐式使用
- `compare_and_swap` 在 Task 1.3 定义，Task 3.1 引用
- `request_cancel` 在 Task 2.1 定义，Task 2.3/3.1 引用
- `can_stop` / `can_delete` 在 Task 1.3 定义，Task 3.1/3.3 引用
- `list_all` 在 Task 1.2 定义，Task 3.2 引用
- `JobStateStore.delete` 在 Task 3.3 定义，Task 3.3 内部使用
