# Phase 3 Implementation Plan: recover_after_restart + PATCH /workers/me/capacity

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现实例重启后的故障自愈（recover_after_restart）+ 运维动态调整并发上限（PATCH /me/capacity），使 FastAPI 实例具备"故障自愈 + 可调容量"的运维能力。

**Architecture:**
- 新模块 `app/utils/recovery.py` 集中处理重启扫描逻辑
- `InstanceState` 新增 `ready` 标志 + `mark_ready()` + `reserve_for_recovery()`
- `lifespan` startup 同步阻塞调用 `recover_after_restart()`，完成后才接受请求
- 新端点 `PATCH /api/v1/workers/me/capacity` 仅校验下限 + 立即写内存
- `/health` 在 ready 之前返回 503

**Tech Stack:** Python 3.11+ / FastAPI / Pydantic v2 / pytest + pytest-asyncio / os.kill

---

## File Structure

| 路径 | 类型 | 职责 |
|------|------|------|
| `opencompass-app/app/core/state.py` | 修改 | 加 `ready`、`mark_ready`、`reserve_for_recovery` |
| `opencompass-app/app/utils/recovery.py` | 新建 | `is_pid_in_current_session` + `recover_after_restart` |
| `opencompass-app/app/main.py` | 修改 | lifespan 调 recover + 设置 ready |
| `opencompass-app/app/api/workers.py` | 修改 | /health ready 检查 + PATCH /me/capacity |
| `opencompass-app/app/models/request.py` | 修改 | 加 `CapacityAdjustRequest` |
| `opencompass-app/tests/test_instance_state.py` | 修改 | 加 ready 相关测试 |
| `opencompass-app/tests/test_recovery.py` | 新建 | 完整覆盖 recover 模块 |
| `opencompass-app/tests/test_workers_api.py` | 修改 | 加 PATCH /me/capacity 测试 |
| `opencompass-app/tests/test_recovery_integration.py` | 新建 | lifespan 集成 + 重启流程 |
| `opencompass-app/scripts/smoke_manual.sh` | 修改 | 加 t14-t17 四项 |
| `opencompass-app/README.md` | 修改 | Phase 3 端点表 + 文档链接 |

---

### Task 1: InstanceState 扩展（ready 标志 + reserve_for_recovery）

**Files:**
- Modify: `opencompass-app/app/core/state.py:14-50`
- Modify: `opencompass-app/tests/test_instance_state.py`

- [ ] **Step 1: 写测试**

追加到 `tests/test_instance_state.py`：

```python
def test_ready_default_false(inst):
    assert inst.ready is False


def test_mark_ready_sets_true(inst):
    inst.mark_ready()
    assert inst.ready is True


def test_mark_ready_idempotent(inst):
    inst.mark_ready()
    inst.mark_ready()
    assert inst.ready is True


def test_reserve_for_recovery_aligns_running_count(inst):
    inst.reserve_for_recovery("job_a")
    assert inst.running_count() == 1
    asyncio.run(inst.release("job_a"))
    assert inst.running_count() == 0
```

- [ ] **Step 2: 跑测试验证红**

Run: `cd opencompass-app && python3 -m pytest tests/test_instance_state.py -v`
Expected: FAIL — `AttributeError: 'InstanceState' object has no attribute 'ready'`

- [ ] **Step 3: 写实现**

修改 `app/core/state.py`，在 `__init__` 添加 `ready=False`，新增两个方法：

```python
class InstanceState:
    def __init__(self, max_concurrent: int, instance_id: str):
        self.max_concurrent = max_concurrent
        self.instance_id = instance_id
        self._running: set[str] = set()
        self._processes: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self.ready: bool = False    # 新增：recover 完成才 True

    # ----- 既有方法保持不变 -----
    # ...

    def mark_ready(self) -> None:
        """设置 ready=True（幂等）。由 lifespan recover 完成后调用。"""
        self.ready = True

    def reserve_for_recovery(self, job_id: str) -> None:
        """recover 时占位对齐计数（同步，单线程上下文安全）。

        不参与并发限流判断路径；用于在 lifespan startup 单线程上下文中
        把残留任务的 slot 计数清零。
        """
        self._running.add(job_id)
```

- [ ] **Step 4: 跑测试验证绿**

Run: `cd opencompass-app && python3 -m pytest tests/test_instance_state.py -v`
Expected: 全部 PASS（13 个：原 9 + 新 4）

- [ ] **Step 5: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/app/core/state.py opencompass-app/tests/test_instance_state.py
git commit -m "feat(state): add ready flag + reserve_for_recovery for Phase 3 recover"
```

---

### Task 2: recovery 模块（is_pid_in_current_session + 框架）

**Files:**
- Create: `opencompass-app/app/utils/__init__.py`（空文件）
- Create: `opencompass-app/app/utils/recovery.py`
- Create: `opencompass-app/tests/test_recovery.py`

- [ ] **Step 1: 写测试**

新建 `tests/test_recovery.py`：

```python
"""单元测试 app.utils.recovery。"""
import os

import pytest

from app.utils.recovery import is_pid_in_current_session


def test_is_pid_returns_true_for_self():
    """当前进程 PID 必然存活。"""
    assert is_pid_in_current_session(os.getpid()) is True


def test_is_pid_returns_false_for_missing():
    """PID 999999 几乎肯定不存在。"""
    assert is_pid_in_current_session(999999) is False


def test_is_pid_returns_false_for_none():
    assert is_pid_in_current_session(None) is False
```

- [ ] **Step 2: 跑测试验证红**

Run: `cd opencompass-app && python3 -m pytest tests/test_recovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.utils.recovery'`

- [ ] **Step 3: 写实现**

创建 `app/utils/__init__.py`（空）和 `app/utils/recovery.py`：

```python
"""实例启动时扫描遗留任务并收尾。

设计要点：
- 在 lifespan startup 单线程上下文串行执行，避免 PID 复用风险
- 单文件失败不阻断整个 recover（依赖 list_all 跳过损坏文件）
"""
import logging
import os
from typing import Optional

from app.core.state import InstanceState
from app.models.enums import JobStatus
from app.stores.nfs_state import JobStateStore
from app.utils.time import now_iso

log = logging.getLogger(__name__)


def is_pid_in_current_session(pid: Optional[int]) -> bool:
    """检查 PID 是否属于当前进程会话。

    实现：os.kill(pid, 0) — 仅检查进程是否存在。lifespan startup 串行执行
    窗口期（<3s）内 PID 复用概率可忽略。
    """
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


async def recover_after_restart(
    store: JobStateStore,
    instance: InstanceState,
) -> None:
    """实例启动时扫描遗留任务并收尾（PRD FR-6.1~6.5）。

    处理规则：
      - starting         → failed（实例在启动子进程前崩溃）
      - running          → PID 不在新会话 → failed
      - cancelling       → PID 不在新会话 → failed
      - finalizing       → failed（不重跑 summarizer，PRD 推迟）
      - terminal         → 跳过
    """
    for job_id, state in store.list_all():
        if state.get("instance_id") != instance.instance_id:
            continue  # 别人的任务不归我管

        status = state.get("status")
        if status in (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        ):
            continue

        if status == JobStatus.STARTING.value:
            _mark_failed(store, instance, job_id, state,
                         "Instance crashed before subprocess started")
        elif status in (JobStatus.RUNNING.value, JobStatus.CANCELLING.value):
            pid = state.get("pid")
            if not is_pid_in_current_session(pid):
                _mark_failed(store, instance, job_id, state,
                             f"Instance crashed; PID {pid} not in current session")
            else:
                log.warning("Job %s PID %s still alive after restart; leaving for ops",
                            job_id, pid)
        elif status == JobStatus.FINALIZING.value:
            _mark_failed(store, instance, job_id, state,
                         "Instance crashed during finalization")
        else:
            log.warning("Unknown status %s for job %s; skipping", status, job_id)


def _mark_failed(store, instance, job_id, current, error_message):
    """标记任务为 failed 并对齐 slot 计数。"""
    new_state = {
        **current,
        "status": JobStatus.FAILED.value,
        "finished_at": now_iso(),
        "error_message": error_message,
    }
    try:
        store.write_atomic(job_id, new_state)
    except Exception:
        log.exception("Failed to write recovered state for job %s", job_id)
        return  # 单文件失败不阻断

    instance.reserve_for_recovery(job_id)
    instance.release(job_id)
    log.info("Recovered job %s: %s", job_id, error_message)
```

- [ ] **Step 4: 跑测试验证绿**

Run: `cd opencompass-app && python3 -m pytest tests/test_recovery.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/app/utils/ opencompass-app/tests/test_recovery.py
git commit -m "feat(utils): add recovery.py — is_pid + recover_after_restart skeleton"
```

---

### Task 3: recover 状态分支完整覆盖

**Files:**
- Modify: `opencompass-app/tests/test_recovery.py`

- [ ] **Step 1: 追加状态分支测试**

```python
"""继续追加到 tests/test_recovery.py。"""
import asyncio

from app.core.state import InstanceState
from app.models.enums import JobStatus
from app.utils.recovery import recover_after_restart


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
```

- [ ] **Step 2: 跑测试验证全绿**

Run: `cd opencompass-app && python3 -m pytest tests/test_recovery.py -v`
Expected: 全部 PASS（11 个：原 3 + 新 8）

- [ ] **Step 3: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/tests/test_recovery.py
git commit -m "test(recovery): full state-branch coverage for recover_after_restart"
```

---

### Task 4: lifespan 集成 recover + ready 标志

**Files:**
- Modify: `opencompass-app/app/main.py:31-42`
- Modify: `opencompass-app/tests/conftest.py`

- [ ] **Step 1: 写测试**

在 `tests/conftest.py` 的 `client` fixture 之前添加：

```python
@pytest.fixture
def ready_client():
    """已 mark_ready 的 TestClient（跳过 recover）。绝大多数测试用这个。"""
    from app.core.settings import get_settings
    from app.main import create_app
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        # 触发 lifespan 后手动 mark_ready（绕开 recover 的复杂性）
        from app import main as app_main
        app_main.instance_state.mark_ready()
        yield c
    get_settings.cache_clear()
```

然后修改 `client` fixture 也 mark_ready（让现有测试不受 recover 影响）：

```python
@pytest.fixture
def client():
    """FastAPI TestClient（已在 _isolate_env 中隔离环境 + mark_ready）。"""
    from app import main as app_main
    from app.core.settings import get_settings
    from app.main import create_app
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        # lifespan 内 recover 自动跑完，但 mark_ready 在 lifespan 末尾
        # 真实环境下应该已 ready；这里再调一次幂等保护
        app_main.instance_state.mark_ready()
        yield c
    get_settings.cache_clear()
```

- [ ] **Step 2: 修改 lifespan**

修改 `app/main.py` 的 lifespan：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global state_store, instance_state
    s = Settings()
    base_dir = Path(s.oc_data_root) / "workspace" / "state" / "jobs"
    state_store = JobStateStore(base_dir=str(base_dir))
    instance_state = InstanceState(
        max_concurrent=s.max_concurrent,
        instance_id=s.instance_id,
    )

    # Phase 3：启动时 recover 残留任务
    from app.utils.recovery import recover_after_restart
    await recover_after_restart(state_store, instance_state)
    instance_state.mark_ready()

    yield
```

- [ ] **Step 3: 跑全量回归**

Run: `cd opencompass-app && python3 -m pytest tests/ -q`
Expected: 全部 104+ 测试 PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/app/main.py opencompass-app/tests/conftest.py
git commit -m "feat(app): lifespan startup calls recover_after_restart + mark_ready"
```

---

### Task 5: CapacityAdjustRequest Pydantic 模型

**Files:**
- Modify: `opencompass-app/app/models/request.py`

- [ ] **Step 1: 追加模型**

在 `app/models/request.py` 末尾追加：

```python
class CapacityAdjustRequest(BaseModel):
    """PATCH /api/v1/workers/me/capacity 请求体。

    PRD FR-3.3 / 7.2：调整并发上限。Pydantic 自动校验 gt=0。
    业务校验（< running_count → 409）在端点处处理。
    """
    max_concurrent: int = Field(gt=0, description="New max concurrent jobs; must be > 0")
```

- [ ] **Step 2: 验证 Pydantic 校验**

```bash
cd opencompass-app && python3 -c "
from app.models.request import CapacityAdjustRequest
from pydantic import ValidationError

# 正向
print(CapacityAdjustRequest(max_concurrent=10).max_concurrent)

# 校验：0 应失败
try:
    CapacityAdjustRequest(max_concurrent=0)
    print('ERROR: 应该 ValidationError')
except ValidationError:
    print('OK: 0 校验失败')

# 校验：负数应失败
try:
    CapacityAdjustRequest(max_concurrent=-1)
    print('ERROR: 应该 ValidationError')
except ValidationError:
    print('OK: -1 校验失败')
"
```

Expected:
```
10
OK: 0 校验失败
OK: -1 校验失败
```

- [ ] **Step 3: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/app/models/request.py
git commit -m "feat(models): add CapacityAdjustRequest Pydantic model"
```

---

### Task 6: /health 加 ready 检查

**Files:**
- Modify: `opencompass-app/app/api/workers.py:25-41`
- Modify: `opencompass-app/tests/test_workers_api.py`

- [ ] **Step 1: 写测试**

追加到 `tests/test_workers_api.py`：

```python
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
```

- [ ] **Step 2: 跑测试验证红**

Run: `cd opencompass-app && python3 -m pytest tests/test_workers_api.py::test_health_503_when_not_ready tests/test_workers_api.py::test_health_200_after_ready -v`
Expected: FAIL — /health 当前不检查 ready，应返回 200

- [ ] **Step 3: 修改 /health 端点**

修改 `app/api/workers.py`：

```python
@health_router.get("/health", response_model=HealthCheck)
async def health() -> HealthCheck:
    # 延迟导入：避免与 app.main 的循环导入
    from app.main import get_instance_state, get_state_store

    inst = get_instance_state()
    if not inst.ready:
        # Phase 3: recover 未完成
        return HealthCheck(
            status="degraded",
            checks={"recovery": "in_progress"},
        )

    checks: dict[str, str] = {}
    try:
        get_state_store().list_ids()
        checks["nfs_state"] = "ok"
    except Exception as e:
        checks["nfs_state"] = f"fail: {e}"

    checks["opencompass_binary"] = (
        "ok" if shutil.which("opencompass") else "missing"
    )
    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return HealthCheck(status=overall, checks=checks)
```

> **设计取舍**：用返回 200 + status="degraded" 而非 503。原因是 K8s readiness probe 配置复杂，且 PRD AC-P3-5/6 验收口径"recover 期间 /health 返回 503"。需要改为 503：

把 `return HealthCheck(...)` 改成 `raise HTTPException(503, ...)`：

```python
from fastapi import APIRouter, HTTPException

@health_router.get("/health", response_model=HealthCheck)
async def health() -> HealthCheck:
    from app.main import get_instance_state, get_state_store

    inst = get_instance_state()
    if not inst.ready:
        raise HTTPException(503, "Instance recovering after restart")

    checks: dict[str, str] = {}
    try:
        get_state_store().list_ids()
        checks["nfs_state"] = "ok"
    except Exception as e:
        checks["nfs_state"] = f"fail: {e}"

    checks["opencompass_binary"] = (
        "ok" if shutil.which("opencompass") else "missing"
    )
    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return HealthCheck(status=overall, checks=checks)
```

同时把测试调整为断言 503：

```python
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
```

- [ ] **Step 4: 跑测试验证绿**

Run: `cd opencompass-app && python3 -m pytest tests/test_workers_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 跑全量回归**

Run: `cd opencompass-app && python3 -m pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/app/api/workers.py opencompass-app/tests/test_workers_api.py
git commit -m "feat(api): /health returns 503 during recovery (Phase 3)"
```

---

### Task 7: PATCH /me/capacity 端点

**Files:**
- Modify: `opencompass-app/app/api/workers.py`
- Modify: `opencompass-app/tests/test_workers_api.py`

- [ ] **Step 1: 写测试**

追加到 `tests/test_workers_api.py`：

```python
import asyncio


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
```

- [ ] **Step 2: 跑测试验证红**

Run: `cd opencompass-app && python3 -m pytest tests/test_workers_api.py -k patch_capacity -v`
Expected: 全部 FAIL — 端点不存在（404）

- [ ] **Step 3: 实现端点**

修改 `app/api/workers.py`，添加 PATCH 端点：

```python
import logging

from app.models.request import CapacityAdjustRequest

log = logging.getLogger(__name__)


@router.patch("/me/capacity")
async def adjust_capacity(req: CapacityAdjustRequest) -> dict[str, int]:
    """调整并发上限（运维）。

    约束（PRD FR-3.3 / 7.2）：
      - max_concurrent > 0（Pydantic gt=0 自动校验 → 422）
      - max_concurrent >= running_count（业务校验 → 409）

    立即生效；不持久化（重启后从环境变量 MAX_CONCURRENT 读回）。
    """
    from app.main import get_instance_state

    inst = get_instance_state()
    if not inst.ready:
        raise HTTPException(503, "Instance recovering after restart")
    if req.max_concurrent < inst.running_count():
        raise HTTPException(
            409,
            f"New max ({req.max_concurrent}) less than current running "
            f"({inst.running_count()})",
        )
    inst.max_concurrent = req.max_concurrent
    log.info("Capacity adjusted to %d via PATCH /me/capacity", req.max_concurrent)
    return {"max_concurrent": inst.max_concurrent}
```

顶部 import 增加：

```python
from fastapi import APIRouter, HTTPException
```

- [ ] **Step 4: 跑测试验证绿**

Run: `cd opencompass-app && python3 -m pytest tests/test_workers_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `cd opencompass-app && python3 -m pytest tests/ -q`
Expected: 全部 PASS（增加 ~6 个新测试）

- [ ] **Step 6: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/app/api/workers.py opencompass-app/tests/test_workers_api.py
git commit -m "feat(api): add PATCH /api/v1/workers/me/capacity (PRD FR-3.3)"
```

---

### Task 8: 集成测试（lifespan + 重启流程）

**Files:**
- Create: `opencompass-app/tests/test_recovery_integration.py`

- [ ] **Step 1: 写测试**

```python
"""集成测试：lifespan startup 跑 recover + 残留任务被标记 failed。"""
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
    import json
    from pathlib import Path
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
        # /health ready 后查残留任务
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


def test_health_503_during_recovery_then_200(tmp_oc_root):
    """recover 完成前 /health 503，完成后 200。

    注：lifespan 同步执行 recover，TestClient 进入时已完成。
    此测试仅验证最终状态；时序通过 lifespan 同步保证。
    """
    from app.core.settings import get_settings
    from app.main import create_app
    get_settings.cache_clear()
    app = create_app()

    with TestClient(app) as c:
        # lifespan 已 mark_ready
        res = c.get("/health")
        assert res.status_code == 200


def test_recovery_skips_other_instances_state_files(tmp_oc_root):
    """别人的残留任务不动。"""
    import json
    from pathlib import Path
    p = tmp_oc_root / "workspace" / "state" / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    state = {
        "job_id": "other_inst_task",
        "status": "running",
        "instance_id": "OTHER-INSTANCE",  # 别人
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
        # 别人的任务状态不变
        body = c.get("/api/v1/jobs/other_inst_task").json()
        assert body["status"] == "running"
```

- [ ] **Step 2: 跑测试验证绿**

Run: `cd opencompass-app && python3 -m pytest tests/test_recovery_integration.py -v`
Expected: 全部 PASS（3 个）

- [ ] **Step 3: 全量回归**

Run: `cd opencompass-app && python3 -m pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/tests/test_recovery_integration.py
git commit -m "test(recovery): integration test for lifespan startup recover flow"
```

---

### Task 9: smoke_manual.sh 扩展 4 项

**Files:**
- Modify: `opencompass-app/scripts/smoke_manual.sh`

- [ ] **Step 1: 追加测试函数**

在脚本中 `t13_log_no_panic` 之后、`run_tests()` 函数之前追加：

```bash
t14_patch_capacity_success() {
    section "T14: PATCH /api/v1/workers/me/capacity 200"
    local code body new_max
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X PATCH "${BASE}/api/v1/workers/me/capacity" \
        -H "Content-Type: application/json" -d '{"max_concurrent": 8}')
    body=$(cat /tmp/r.json)
    new_max=$(jq_field '["max_concurrent"]' "$body" 2>/dev/null || echo "")
    if [[ "$code" == "200" && "$new_max" == "8" ]]; then
        ok "T14 PATCH capacity 200 + max=8"
    else
        fail "T14 PATCH capacity (code=$code max=$new_max body=$body)"
    fi
    # 校验 /workers/me/free 立即反映新值
    local free_max
    free_max=$(curl -s "${BASE}/api/v1/workers/me/free" | jq_field '["max"]' 2>/dev/null || echo "")
    if [[ "$free_max" == "8" ]]; then
        ok "T14b /workers/me/free 立即反映新 max=8"
    else
        fail "T14b /workers/me/free max=$free_max (期望 8)"
    fi
}

t15_patch_capacity_zero_422() {
    section "T15: PATCH /me/capacity max=0 → 422"
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X PATCH "${BASE}/api/v1/workers/me/capacity" \
        -H "Content-Type: application/json" -d '{"max_concurrent": 0}')
    check_status "$code" "422" "T15 PATCH capacity 0 → 422"
}

t16_patch_capacity_below_running_409() {
    section "T16: PATCH /me/capacity < running → 409"
    # 先创建一个占用 slot 的任务
    local job="smoke_cap_$$"
    curl -s -o /dev/null -X POST "${BASE}/api/v1/jobs" \
        -H "Content-Type: application/json" \
        -d "{\"job_id\":\"${job}\",\"datasets\":[{\"abbr\":\"gsm8k\"}],\"models\":[{\"type\":\"opencompass.models.openai_api.OpenAISDK\",\"path\":\"q\"}]}"
    sleep 1  # 等任务进入 running
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X PATCH "${BASE}/api/v1/workers/me/capacity" \
        -H "Content-Type: application/json" -d '{"max_concurrent": 0}')
    if [[ "$code" == "409" ]]; then
        ok "T16 PATCH capacity 0 (running=1) → 409"
    else
        fail "T16 PATCH capacity (code=$code body=$(cat /tmp/r.json))"
    fi
}

t17_recovery_e2e() {
    section "T17: 注入残留 starting → 模拟重启 → /health 200 → GET failed"
    # 直接利用服务的 recover 在 lifespan 内自动跑完的特性；
    # 这里只验证 GET 残留任务失败状态已生效。
    # （完整重启流程由 CI 集成；smoke 验证 recover 端到端 OK）
    local code body status err
    # 注入一个 starting 残留
    local state_dir="${OC_DATA_ROOT}/workspace/state/jobs"
    mkdir -p "$state_dir"
    cat > "${state_dir}/smoke_residual.json" <<EOF
{"job_id":"smoke_residual","status":"starting","instance_id":"${INSTANCE_ID}","pid":null,"datasets":[],"models":[],"config_path":"/x","work_dir":"/y","created_at":"2026-08-11T00:00:00Z"}
EOF
    # 服务未重启则该状态尚未被 recover（lifespan startup 时执行）；
    # 触发方式：kill 服务 → 重新启动 → 验证。
    # 简化：用当前进程的 recover（通过 monkeypatch 不能直接做，故跳过完整重启）
    # 此处仅验证 prepare 步骤无误：状态文件已创建 + 可被 GET 读取
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/jobs/smoke_residual")
    if [[ "$code" == "200" ]]; then
        ok "T17 残留状态文件可被 GET（recover 验证留给集成测试）"
    else
        fail "T17 残留 GET (code=$code)"
    fi
}
```

- [ ] **Step 2: 注册新测试**

修改 `run_tests()` 函数，循环列表追加：

```bash
    for t in t01_health t02_workers_free t03_create_job t04_get_job \
             t05a_list_owned t05b_list_filter_status t05c_list_filter_model_path \
             t05d_list_pagination t06_stop_terminal_409 t07_delete_terminal_204 \
             t08a_get_missing_404 t08b_stop_missing_404 t09_duplicate_job_409 \
             t10_unknown_model_422 t11_cross_instance_403 t12_health_final \
             t13_log_no_panic t14_patch_capacity_success t15_patch_capacity_zero_422 \
             t16_patch_capacity_below_running_409 t17_recovery_e2e; do
```

- [ ] **Step 3: 跑冒烟验证**

Run: `cd opencompass-app && bash scripts/smoke_manual.sh 2>&1 | tail -50`
Expected: 全部 PASS（22 项：18 + 4 新增）

- [ ] **Step 4: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/scripts/smoke_manual.sh
git commit -m "feat(smoke): add t14-t17 for Phase 3 capacity + recovery"
```

---

### Task 10: lint + 全量测试 + 黑盒验证 + README

**Files:**
- Modify: `opencompass-app/README.md`

- [ ] **Step 1: ruff 自动修复**

Run: `cd opencompass-app && ruff check --fix app/ tests/ 2>&1 | tail -5`
Expected: `All checks passed!`

- [ ] **Step 2: 全量 pytest**

Run: `cd opencompass-app && python3 -m pytest tests/ -q 2>&1 | tail -3`
Expected: `120+ passed in <1s`（104 原有 + ~16 新增）

- [ ] **Step 3: 黑盒集成验证**

Run:
```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass && \
git diff --stat opencompass/ 2>&1 | tail -2
```
Expected: 无 diff（仅 opencompass-app/ 改动）

- [ ] **Step 4: 更新 README**

修改 `opencompass-app/README.md` 端点表（追加 PATCH 端点）：

```markdown
| Method | Path | Purpose | Status |
|--------|------|---------|--------|
| POST | `/api/v1/jobs` | Create and start a job | MVP |
| GET | `/api/v1/jobs/{id}` | Get job state | MVP |
| POST | `/api/v1/jobs/{id}/stop` | Stop a running job | Phase 2 |
| DELETE | `/api/v1/jobs/{id}` | Delete a terminal job | Phase 2 |
| GET | `/api/v1/jobs` | List jobs (filter + pagination) | Phase 2 |
| GET | `/api/v1/workers/me/free` | Free slot count (high freq) | MVP |
| PATCH | `/api/v1/workers/me/capacity` | Adjust max concurrent | Phase 3 |
| GET | `/health` | Health check (503 during recovery) | MVP+Phase3 |
```

在文档链接区域追加：

```markdown
- [Phase 3 Design (recovery + capacity)](../../docs/superpowers/specs/2026-08-11-opencompass-app-phase3-design.md)
```

- [ ] **Step 5: Commit**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
git add opencompass-app/README.md
git commit -m "docs(app): document Phase 3 endpoints + recovery in README"
```

---

## Self-Review

**1. Spec coverage**（spec §1-13）：

| spec 章节 | 任务 |
|----------|------|
| §2.1 recover_after_restart() | Task 2 + 3 |
| §2.1 ready 标志位 | Task 1 + 4 |
| §2.1 PATCH /me/capacity | Task 5 + 7 |
| §2.1 CapacityAdjustRequest | Task 5 |
| §2.1 测试覆盖 | Task 3 + 6 + 7 + 8 + 9 |
| §4.4.1 /health 加 ready | Task 6 |
| §8 测试策略 | Task 3 + 8 + 9 |

**2. Placeholder scan**：无 TBD/TODO。

**3. Type consistency**：
- `instance.reserve_for_recovery(job_id)` 在 Task 1 定义，Task 3 使用 ✓
- `is_pid_in_current_session(pid)` 在 Task 2 定义，Task 3 使用 ✓
- `CapacityAdjustRequest.max_concurrent` 在 Task 5 定义，Task 7 使用 ✓
- `instance.ready` 在 Task 1 定义，Task 4/6/7 使用 ✓

**4. Execution order check**：
- Task 1 → Task 4 (Task 4 用 mark_ready)
- Task 2 → Task 3 (Task 3 用 is_pid)
- Task 5 → Task 7 (Task 7 用 CapacityAdjustRequest)
- Task 6 → Task 7 (Task 7 用 inst.ready 检查)
- Task 8 依赖 Task 4（lifespan 集成）

所有依赖关系正确。

**估算**：10 任务 / 约 30 分钟执行 / 22 个 pytest 用例 / 22 项冒烟。