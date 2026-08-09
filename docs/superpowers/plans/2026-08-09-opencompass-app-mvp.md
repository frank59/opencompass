# OpenCompass-App MVP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `opencompass-app/` 子项目的最小闭环 FastAPI 调度服务，覆盖 4 个核心端点（POST /jobs、GET /jobs/{id}、/workers/me/free、/health），含 30+ 单元测试与 API 集成测试。

**Architecture:** 黑盒集成 OpenCompass（不修改其源码）。FastAPI 子进程通过 `asyncio.create_subprocess_exec` 调用 `opencompass <config> -w ... -r ...`；config 文件由 `app/oc_config/generator.py` 动态拼装（mmengine `read_base()` + 内联 dict）；任务状态以 JSON 原子写入 `${OC_DATA_ROOT}/workspace/state/jobs/`；并发上限由 in-memory `InstanceState` 守护。

**Tech Stack:** Python 3.10+、FastAPI 0.110+、Pydantic 2.5+、pydantic-settings、PyYAML、asyncio；测试用 pytest + pytest-asyncio + httpx。

**Spec Reference:** [`docs/superpowers/specs/2026-08-09-opencompass-app-mvp-design.md`](../specs/2026-08-09-opencompass-app-mvp-design.md)

---

## 文件结构总览

### 创建的文件

```
opencompass-app/
├── pyproject.toml                                  # Task 1.2
├── requirements.txt                                # Task 1.3
├── .gitignore                                      # Task 1.3
├── README.md                                       # Task 7.2
├── app/
│   ├── __init__.py                                 # Task 1.1
│   ├── main.py                                     # Task 6.3
│   ├── api/
│   │   ├── __init__.py                             # Task 1.1
│   │   ├── jobs.py                                 # Task 6.2
│   │   └── workers.py                              # Task 6.1
│   ├── core/
│   │   ├── __init__.py                             # Task 1.1
│   │   ├── settings.py                             # Task 3.3
│   │   ├── instance.py                             # Task 3.3
│   │   ├── state.py                                # Task 3.2
│   │   ├── dataset_registry.py                     # Task 4.2
│   │   ├── model_whitelist.py                      # Task 4.3
│   │   └── dataset_whitelist.py                    # Task 4.4
│   ├── oc_config/
│   │   ├── __init__.py                             # Task 1.1
│   │   └── generator.py                            # Task 5.1
│   ├── executor/
│   │   ├── __init__.py                             # Task 1.1
│   │   └── subprocess_runner.py                    # Task 5.2
│   ├── stores/
│   │   ├── __init__.py                             # Task 1.1
│   │   └── nfs_state.py                            # Task 3.1
│   ├── models/
│   │   ├── __init__.py                             # Task 1.1
│   │   ├── request.py                              # Task 2.4
│   │   ├── response.py                             # Task 2.4
│   │   └── enums.py                                # Task 2.1
│   ├── data/
│   │   └── dataset_index.yaml                      # Task 4.1
│   └── utils/
│       ├── __init__.py                             # Task 1.1
│       ├── time.py                                 # Task 2.3
│       └── ids.py                                  # Task 2.2
└── tests/
    ├── __init__.py                                 # Task 1.1
    ├── conftest.py                                 # Task 1.4
    ├── test_enums.py                               # Task 2.1
    ├── test_utils.py                               # Task 2.2 + 2.3
    ├── test_nfs_state.py                           # Task 3.1
    ├── test_instance_state.py                      # Task 3.2
    ├── test_settings.py                            # Task 3.3
    ├── test_dataset_registry.py                    # Task 4.2
    ├── test_model_whitelist.py                     # Task 4.3
    ├── test_dataset_whitelist.py                   # Task 4.4
    ├── test_generator.py                           # Task 5.1
    ├── test_subprocess_runner.py                   # Task 5.2
    ├── test_jobs_api.py                            # Task 6.2
    └── test_workers_api.py                         # Task 6.1
```

---

## 阶段 1：脚手架

### Task 1.1：创建目录与占位 `__init__.py`

**Files:**
- Create: 全部 `__init__.py` 文件（空文件）

- [ ] **Step 1：创建目录树**

```bash
cd opencompass-app
mkdir -p app/{api,core,oc_config,executor,stores,models,data,utils} tests
touch app/__init__.py \
      app/api/__init__.py \
      app/core/__init__.py \
      app/oc_config/__init__.py \
      app/executor/__init__.py \
      app/stores/__init__.py \
      app/models/__init__.py \
      app/utils/__init__.py \
      tests/__init__.py
ls -R app/ tests/
```

预期：所有目录存在，所有 `__init__.py` 为空文件。

- [ ] **Step 2：Commit**

```bash
git add opencompass-app/
git commit -m "chore(scaffold): create opencompass-app directory tree"
```

---

### Task 1.2：`pyproject.toml`

**Files:**
- Create: `opencompass-app/pyproject.toml`

- [ ] **Step 1：编写 pyproject.toml**

```toml
[project]
name = "opencompass-app"
version = "0.1.0"
description = "FastAPI scheduler for OpenCompass evaluation jobs"
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
ignore = ["E501"]
```

- [ ] **Step 2：验证 ruff 可解析**

```bash
cd opencompass-app
python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))" && echo OK
```

预期：输出 `OK`。

- [ ] **Step 3：Commit**

```bash
git add opencompass-app/pyproject.toml
git commit -m "chore(scaffold): add pyproject.toml with pytest + ruff config"
```

---

### Task 1.3：`requirements.txt` 与 `.gitignore`

**Files:**
- Create: `opencompass-app/requirements.txt`
- Create: `opencompass-app/.gitignore`

- [ ] **Step 1：编写 requirements.txt**

```
fastapi>=0.110,<0.120
uvicorn[standard]>=0.27,<0.30
pydantic>=2.5,<3
pydantic-settings>=2.1,<3
pyyaml>=6.0,<7
httpx>=0.25,<0.30
```

- [ ] **Step 2：编写 .gitignore**

```
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
*.egg-info/
.venv/
venv/
*.tmp
.coverage
htmlcov/
```

- [ ] **Step 3：Commit**

```bash
git add opencompass-app/requirements.txt opencompass-app/.gitignore
git commit -m "chore(scaffold): add requirements.txt and .gitignore"
```

---

### Task 1.4：`tests/conftest.py`（基础 fixture）

**Files:**
- Create: `opencompass-app/tests/conftest.py`

- [ ] **Step 1：编写 conftest.py**

```python
"""全局 pytest fixture。所有测试默认使用隔离 tmp 目录 + pytest-instance 标识。"""
import os
import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """每个测试隔离：OC_DATA_ROOT → tmp_path/oc-root；INSTANCE_ID → pytest-instance。"""
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))
    monkeypatch.setenv("INSTANCE_ID", "pytest-instance")
    monkeypatch.setenv("MAX_CONCURRENT", "4")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    yield
```

- [ ] **Step 2：冒烟测试**

```bash
cd opencompass-app
python3 -m pytest tests/ -v --collect-only 2>&1 | head -10
```

预期：输出显示 collected 0 items（暂无测试用例，但 conftest 解析成功）。

- [ ] **Step 3：Commit**

```bash
git add opencompass-app/tests/conftest.py
git commit -m "test(scaffold): add conftest with autouse env isolation"
```

---

## 阶段 2：枚举、工具与数据模型

### Task 2.1：`app/models/enums.py` + 测试

**Files:**
- Create: `opencompass-app/app/models/enums.py`
- Create: `opencompass-app/tests/test_enums.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_enums.py
from app.models.enums import JobStatus


def test_job_status_values():
    assert JobStatus.STARTING.value == "starting"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.FINALIZING.value == "finalizing"
    assert JobStatus.COMPLETED.value == "completed"
    assert JobStatus.FAILED.value == "failed"


def test_job_status_is_str():
    assert isinstance(JobStatus.RUNNING, str)
    assert JobStatus.RUNNING == "running"


def test_job_status_no_cancelling():
    """MVP 不含 CANCELLING/CANCELLED（Phase 2 再加）。"""
    assert not hasattr(JobStatus, "CANCELLING")
    assert not hasattr(JobStatus, "CANCELLED")
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_enums.py -v
```

预期：`ModuleNotFoundError: No module named 'app.models.enums'`。

- [ ] **Step 3：写最小实现**

```python
# app/models/enums.py
from enum import Enum


class JobStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
```

- [ ] **Step 4：跑测试，确认通过**

```bash
python3 -m pytest tests/test_enums.py -v
```

预期：3 passed。

- [ ] **Step 5：Commit**

```bash
git add app/models/enums.py tests/test_enums.py
git commit -m "feat(models): add JobStatus enum (MVP subset)"
```

---

### Task 2.2：`app/utils/ids.py` + 测试

**Files:**
- Create: `opencompass-app/app/utils/ids.py`
- Modify: `opencompass-app/tests/test_utils.py`（新建，含 ids 测试）

- [ ] **Step 1：写失败测试**

```python
# tests/test_utils.py
import pytest
from app.utils.ids import is_valid_job_id


@pytest.mark.parametrize(
    "job_id,expected",
    [
        ("job_20260808_abc123", True),
        ("abc-XYZ_0", True),
        ("a", True),
        ("a" * 64, True),
        ("", False),
        ("a" * 65, False),
        ("has space", False),
        ("has/slash", False),
        ("中文_abc", False),       # 只允许 ASCII
        ("job.with.dot", False),
        ("abc?", False),
    ],
)
def test_is_valid_job_id(job_id, expected):
    assert is_valid_job_id(job_id) == expected
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_utils.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写最小实现**

```python
# app/utils/ids.py
import re

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_valid_job_id(job_id: str) -> bool:
    """校验 job_id 格式：ASCII 字母/数字/下划线/连字符，长度 1~64。"""
    return bool(_JOB_ID_RE.match(job_id))
```

- [ ] **Step 4：跑测试，确认通过**

```bash
python3 -m pytest tests/test_utils.py -v
```

预期：10 passed。

- [ ] **Step 5：Commit**

```bash
git add app/utils/ids.py tests/test_utils.py
git commit -m "feat(utils): add is_valid_job_id"
```

---

### Task 2.3：`app/utils/time.py` + 测试

**Files:**
- Create: `opencompass-app/app/utils/time.py`
- Modify: `opencompass-app/tests/test_utils.py`（追加 now_iso 测试）

- [ ] **Step 1：追加失败测试**

在 `tests/test_utils.py` 末尾追加：

```python
from app.utils.time import now_iso
import re


def test_now_iso_format():
    s = now_iso()
    # 形如 2026-08-09T10:30:00.523000Z
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", s)


def test_now_iso_is_utc():
    """两次调用应严格非递减。"""
    a = now_iso()
    b = now_iso()
    assert a <= b
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_utils.py -v
```

预期：`ModuleNotFoundError: No module named 'app.utils.time'`。

- [ ] **Step 3：写最小实现**

```python
# app/utils/time.py
from datetime import datetime, timezone


def now_iso() -> str:
    """UTC ISO8601，精确到微秒，例如 2026-08-09T10:30:00.523000Z。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
```

- [ ] **Step 4：跑测试，确认通过**

```bash
python3 -m pytest tests/test_utils.py -v
```

预期：12 passed（10 ids + 2 time）。

- [ ] **Step 5：Commit**

```bash
git add app/utils/time.py tests/test_utils.py
git commit -m "feat(utils): add now_iso helper"
```

---

### Task 2.4：`app/models/request.py` + `response.py`

**Files:**
- Create: `opencompass-app/app/models/request.py`
- Create: `opencompass-app/app/models/response.py`

> 本任务无独立测试，验证通过 Task 6.x 的 API 集成测试覆盖。

- [ ] **Step 1：写 request.py**

```python
# app/models/request.py
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ModelItem(BaseModel):
    """单个模型配置。type 在白名单内；path 为模型名；其他字段透传给 OC 类初始化。"""
    type: str
    path: str
    model_config = ConfigDict(extra="allow")


class DatasetItem(BaseModel):
    """单个数据集配置。
    - 内置数据集：仅含 abbr。
    - 自定义数据集：含 type/path/reader_cfg/infer_cfg/eval_cfg。
    """
    abbr: str
    type: str | None = None
    path: str | None = None
    reader_cfg: dict[str, Any] | None = None
    infer_cfg: dict[str, Any] | None = None
    eval_cfg: dict[str, Any] | None = None


class CreateJobRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=64)
    datasets: list[DatasetItem] = Field(min_length=1)
    models: list[ModelItem] = Field(min_length=1)
    priority: int = 5
    max_runtime_seconds: int = 7200
    created_by: str | None = None
```

- [ ] **Step 2：写 response.py**

```python
# app/models/response.py
from pydantic import BaseModel
from app.models.enums import JobStatus
from app.models.request import DatasetItem, ModelItem


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    instance_id: str
    datasets: list[DatasetItem]
    models: list[ModelItem]
    config_path: str
    work_dir: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    pid: int | None = None
    created_by: str | None = None


class FreeWorkerCount(BaseModel):
    available: int
    max: int
    running: int


class HealthCheck(BaseModel):
    status: str
    checks: dict[str, str]
```

- [ ] **Step 3：冒烟验证 import**

```bash
cd opencompass-app
python3 -c "from app.models.request import CreateJobRequest, DatasetItem, ModelItem; from app.models.response import JobResponse, FreeWorkerCount, HealthCheck; print('imports OK')"
```

预期：输出 `imports OK`。

- [ ] **Step 4：Commit**

```bash
git add app/models/request.py app/models/response.py
git commit -m "feat(models): add request/response Pydantic models"
```

---

## 阶段 3：持久化、并发与配置

### Task 3.1：`app/stores/nfs_state.py`（JobStateStore）

**Files:**
- Create: `opencompass-app/app/stores/nfs_state.py`
- Create: `opencompass-app/tests/test_nfs_state.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_nfs_state.py
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
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_nfs_state.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写最小实现**

```python
# app/stores/nfs_state.py
"""NFS JSON 任务状态持久化。

设计要点：
- 任意实例可读（GET /jobs/{id}）。
- 写者独占（POST /jobs 成功后由创建实例独占）。
- 原子写：tempfile.mkstemp + fsync + os.replace（NFS 友好）。
"""
import json
import os
import tempfile
from pathlib import Path


class JobStateStore:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.base_dir / f"{job_id}.json"

    def write_atomic(self, job_id: str, payload: dict) -> None:
        """原子写：临时文件 → fsync → os.replace（NFS 上保证可见性）。"""
        target = self._path(job_id)
        fd, tmp = tempfile.mkstemp(
            dir=self.base_dir, prefix=f".{job_id}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def read(self, job_id: str) -> dict | None:
        try:
            with open(self._path(job_id), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def exists(self, job_id: str) -> bool:
        return self._path(job_id).exists()

    def list_ids(self) -> list[str]:
        if not self.base_dir.is_dir():
            return []
        return sorted(
            p.stem for p in self.base_dir.glob("*.json")
            if not p.name.startswith(".")
        )
```

- [ ] **Step 4：跑测试，确认通过**

```bash
python3 -m pytest tests/test_nfs_state.py -v
```

预期：6 passed。

- [ ] **Step 5：Commit**

```bash
git add app/stores/nfs_state.py tests/test_nfs_state.py
git commit -m "feat(stores): add JobStateStore with atomic JSON write"
```

---

### Task 3.2：`app/core/state.py`（InstanceState）

**Files:**
- Create: `opencompass-app/app/core/state.py`
- Create: `opencompass-app/tests/test_instance_state.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_instance_state.py
import asyncio
import pytest
from app.core.state import InstanceState


@pytest.fixture
def state():
    return InstanceState(max_concurrent=2)


def test_is_at_capacity_false_when_empty(state):
    assert state.is_at_capacity() is False
    assert state.running_count() == 0
    assert state.available_slots() == 2


@pytest.mark.asyncio
async def test_try_acquire_then_release(state):
    assert await state.try_acquire("job_a") is True
    assert state.running_count() == 1
    assert state.available_slots() == 1
    await state.release("job_a")
    assert state.running_count() == 0


@pytest.mark.asyncio
async def test_try_acquire_returns_false_when_full(state):
    assert await state.try_acquire("job_a") is True
    assert await state.try_acquire("job_b") is True
    assert await state.try_acquire("job_c") is False
    assert state.is_at_capacity() is True


@pytest.mark.asyncio
async def test_release_idempotent(state):
    await state.release("never_acquired")  # 不抛错
    await state.try_acquire("job_a")
    await state.release("job_a")
    await state.release("job_a")  # 第二次释放也不抛错
    assert state.running_count() == 0


@pytest.mark.asyncio
async def test_concurrent_acquire_respects_limit(state):
    """并发 acquire 50 次，最终只应有 max_concurrent 个成功。"""
    state_big = InstanceState(max_concurrent=5)
    results = await asyncio.gather(*[state_big.try_acquire(f"j{i}") for i in range(50)])
    assert sum(results) == 5
    assert state_big.running_count() == 5


@pytest.mark.asyncio
async def test_track_process_then_release(state):
    proc = object()  # 用 object 假装进程；track_process 不做类型校验
    await state.try_acquire("job_a")
    await state.track_process("job_a", proc)  # type: ignore[arg-type]
    await state.release("job_a")
    assert state.running_count() == 0
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_instance_state.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写最小实现**

```python
# app/core/state.py
"""实例级 in-memory worker 池。

设计要点（与设计文档 §5.3 一致）：
- O(1) 读路径（/workers/me/free 热路径）：running_count/available_slots/is_at_capacity 不加锁。
- 写路径（POST /jobs 创建时）：try_acquire/track_process/release 使用 asyncio.Lock。
- 仅保存 job_id 集合与 process 字典，不持久化（实例关闭时丢失符合预期）。
"""
import asyncio
from typing import Any


class InstanceState:
    def __init__(self, max_concurrent: int):
        self.max_concurrent = max_concurrent
        self._running: set[str] = set()
        self._processes: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # O(1) 读路径（无锁，热路径）
    def running_count(self) -> int:
        return len(self._running)

    def available_slots(self) -> int:
        return max(0, self.max_concurrent - len(self._running))

    def is_at_capacity(self) -> bool:
        return len(self._running) >= self.max_concurrent

    # 写路径（加锁）
    async def try_acquire(self, job_id: str) -> bool:
        async with self._lock:
            if self.is_at_capacity():
                return False
            self._running.add(job_id)
            return True

    async def track_process(self, job_id: str, proc: Any) -> None:
        async with self._lock:
            self._processes[job_id] = proc

    async def release(self, job_id: str) -> None:
        async with self._lock:
            self._running.discard(job_id)
            self._processes.pop(job_id, None)


# 全局单例（main.py lifespan 初始化）
instance_state: InstanceState | None = None


def get_instance_state() -> InstanceState:
    if instance_state is None:
        raise RuntimeError("InstanceState not initialized; call init() first")
    return instance_state


def init_instance_state(max_concurrent: int) -> InstanceState:
    global instance_state
    instance_state = InstanceState(max_concurrent=max_concurrent)
    return instance_state
```

- [ ] **Step 4：跑测试，确认通过**

```bash
python3 -m pytest tests/test_instance_state.py -v
```

预期：6 passed。

- [ ] **Step 5：Commit**

```bash
git add app/core/state.py tests/test_instance_state.py
git commit -m "feat(core): add InstanceState (in-memory worker pool)"
```

---

### Task 3.3：`app/core/settings.py` + `app/core/instance.py`

**Files:**
- Create: `opencompass-app/app/core/settings.py`
- Create: `opencompass-app/app/core/instance.py`
- Create: `opencompass-app/tests/test_settings.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_settings.py
import pytest
from app.core.settings import Settings


def test_settings_defaults(monkeypatch):
    # 清除可能存在的 OC_DATA_ROOT
    for k in ["INSTANCE_ID", "OC_DATA_ROOT", "MAX_CONCURRENT", "LOG_LEVEL"]:
        monkeypatch.delenv(k, raising=False)
    s = Settings()
    assert s.oc_data_root == "/data/opencompass"
    assert s.max_concurrent == 8
    assert s.log_level == "INFO"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("OC_DATA_ROOT", "/tmp/test-oc")
    monkeypatch.setenv("MAX_CONCURRENT", "16")
    s = Settings()
    assert s.oc_data_root == "/tmp/test-oc"
    assert s.max_concurrent == 16
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_settings.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写 settings.py**

```python
# app/core/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """环境变量驱动的运行时配置。环境变量名直接对应字段名（大写）。"""
    instance_id: str | None = None
    oc_data_root: str = "/data/opencompass"
    max_concurrent: int = 8
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)


def get_settings() -> Settings:
    """每次返回新实例，便于测试隔离。"""
    return Settings()
```

- [ ] **Step 4：写 instance.py**

```python
# app/core/instance.py
import os
import socket

_INSTANCE_ID: str | None = None


def get_instance_id() -> str:
    """返回 INSTANCE_ID 环境变量，否则 <hostname>-<pid>。"""
    global _INSTANCE_ID
    if _INSTANCE_ID is None:
        env = os.getenv("INSTANCE_ID")
        if env:
            _INSTANCE_ID = env
        else:
            _INSTANCE_ID = f"{socket.gethostname()}-{os.getpid()}"
    return _INSTANCE_ID


def reset_instance_id_cache() -> None:
    """仅测试使用。"""
    global _INSTANCE_ID
    _INSTANCE_ID = None
```

- [ ] **Step 5：跑测试，确认通过**

```bash
python3 -m pytest tests/test_settings.py -v
```

预期：2 passed。

- [ ] **Step 6：Commit**

```bash
git add app/core/settings.py app/core/instance.py tests/test_settings.py
git commit -m "feat(core): add Settings (env-driven) + instance_id helper"
```

---

## 阶段 4：注册表与白名单

### Task 4.1：复制 `dataset-index.yml`

**Files:**
- Create: `opencompass-app/app/data/dataset_index.yaml`（复制自仓库根 `dataset-index.yml`）

- [ ] **Step 1：复制文件**

```bash
cd /Users/wangheng/work/projects/github-frank59/opencompass
cp dataset-index.yml opencompass-app/app/data/dataset_index.yaml
wc -l opencompass-app/app/data/dataset_index.yaml
```

预期：约 1407 行。

- [ ] **Step 2：Commit**

```bash
git add opencompass-app/app/data/dataset_index.yaml
git commit -m "feat(data): bundle dataset_index.yaml (229 OC official datasets)"
```

---

### Task 4.2：`app/core/dataset_registry.py`（DatasetRegistry）

**Files:**
- Create: `opencompass-app/app/core/dataset_registry.py`
- Create: `opencompass-app/tests/test_dataset_registry.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_dataset_registry.py
from app.core.dataset_registry import DatasetRegistry


def test_is_builtin_known():
    assert DatasetRegistry.is_builtin("gsm8k") is True
    assert DatasetRegistry.is_builtin("mmlu") is True


def test_is_builtin_unknown():
    assert DatasetRegistry.is_builtin("nonexistent_dataset_xyz") is False


def test_resolve_builtin_returns_module_and_var():
    mod, var = DatasetRegistry.resolve_builtin("gsm8k")
    assert mod == "opencompass.configs.datasets.gsm8k.gsm8k_gen"
    assert var == "gsm8k_datasets"


def test_resolve_builtin_unknown_raises():
    import pytest
    with pytest.raises(KeyError, match="nonexistent_xyz"):
        DatasetRegistry.resolve_builtin("nonexistent_xyz")


def test_resolve_mmlu():
    mod, var = DatasetRegistry.resolve_builtin("mmlu")
    assert mod == "opencompass.configs.datasets.mmlu.mmlu_gen"
    assert var == "mmlu_datasets"
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_dataset_registry.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写最小实现**

```python
# app/core/dataset_registry.py
"""内置数据集查表。

数据源：app/data/dataset_index.yaml（OC 官方维护的 229 项数据集索引）。
转换规则：configpath = opencompass/configs/datasets/<dir>/<file>.py
       → module_path = opencompass.configs.datasets.<dir>.<file>
       → var_name     = <dir>_datasets
"""
from pathlib import Path
import yaml


class DatasetRegistry:
    _INDEX: dict[str, tuple[str, str]] | None = None  # abbr -> (module_path, var_name)

    @classmethod
    def _load(cls) -> dict[str, tuple[str, str]]:
        if cls._INDEX is not None:
            return cls._INDEX
        path = Path(__file__).parent / "data" / "dataset_index.yaml"
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        idx: dict[str, tuple[str, str]] = {}
        for entry in raw:
            (abbr, info), = entry.items()
            cfg_path: str = info["configpath"]
            module_path = cfg_path.removesuffix(".py").replace("/", ".")
            var_name = f"{Path(cfg_path).parent.name}_datasets"
            idx[abbr] = (module_path, var_name)
        cls._INDEX = idx
        return idx

    @classmethod
    def is_builtin(cls, abbr: str) -> bool:
        return abbr in cls._load()

    @classmethod
    def resolve_builtin(cls, abbr: str) -> tuple[str, str]:
        index = cls._load()
        if abbr not in index:
            raise KeyError(f"dataset '{abbr}' not in registry")
        return index[abbr]
```

- [ ] **Step 4：跑测试，确认通过**

```bash
python3 -m pytest tests/test_dataset_registry.py -v
```

预期：5 passed。

- [ ] **Step 5：Commit**

```bash
git add app/core/dataset_registry.py tests/test_dataset_registry.py
git commit -m "feat(core): add DatasetRegistry backed by dataset_index.yaml"
```

---

### Task 4.3：`app/core/model_whitelist.py`（ModelWhitelist）

**Files:**
- Create: `opencompass-app/app/core/model_whitelist.py`
- Create: `opencompass-app/tests/test_model_whitelist.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_model_whitelist.py
import pytest
from app.core.model_whitelist import ModelWhitelist


def test_validate_missing_type():
    with pytest.raises(ValueError, match="missing 'type' field"):
        ModelWhitelist.validate({"path": "abc"})


def test_validate_missing_path():
    with pytest.raises(ValueError, match="missing 'path' field"):
        ModelWhitelist.validate({"type": "opencompass.models.openai_api.OpenAI"})


def test_validate_unknown_type():
    with pytest.raises(ValueError, match="not in whitelist"):
        ModelWhitelist.validate({
            "type": "opencompass.models.does_not_exist.FakeModel",
            "path": "abc",
        })


def test_types_fallback_empty_when_oc_not_installed(monkeypatch):
    """本机未装 OC 时，白名单 fallback 为空集合，不抛错。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("opencompass"):
            raise ImportError("simulated: opencompass not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # 清除缓存
    ModelWhitelist._TYPES = None
    types = ModelWhitelist.types()
    assert types == frozenset()
    ModelWhitelist._TYPES = None  # 还原


def test_validate_passes_with_empty_whitelist(monkeypatch):
    """白名单为空时，任何 type 都失败（防止漏装 OC 导致放行）。"""
    monkeypatch.setattr(ModelWhitelist, "_TYPES", frozenset())
    with pytest.raises(ValueError, match="not in whitelist"):
        ModelWhitelist.validate({"type": "anything", "path": "x"})
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_model_whitelist.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写最小实现**

```python
# app/core/model_whitelist.py
"""模型类型白名单。

扫描策略（黑盒集成约束 §1.1）：
- 运行时扫描 opencompass.models 包下所有 BaseAPIModel 子类。
- 本机未装 OC 时白名单为空 + warning 日志。
- 严禁硬编码类名字符串。
"""
import logging

log = logging.getLogger(__name__)


class ModelWhitelist:
    _TYPES: frozenset[str] | None = None

    @classmethod
    def types(cls) -> frozenset[str]:
        if cls._TYPES is not None:
            return cls._TYPES
        try:
            import opencompass.models as pkg
            from opencompass.models.base_api import BaseAPIModel
            found: set[str] = set()
            for name in dir(pkg):
                obj = getattr(pkg, name)
                if isinstance(obj, type) and issubclass(obj, BaseAPIModel) and obj is not BaseAPIModel:
                    found.add(f"opencompass.models.{obj.__name__}")
            cls._TYPES = frozenset(found)
        except ImportError:
            log.warning("opencompass not installed; model whitelist is empty")
            cls._TYPES = frozenset()
        return cls._TYPES

    @classmethod
    def validate(cls, model_dict: dict) -> None:
        if not model_dict.get("type"):
            raise ValueError("missing 'type' field")
        if not model_dict.get("path"):
            raise ValueError("missing 'path' field")
        if model_dict["type"] not in cls.types():
            raise ValueError(
                f"model type '{model_dict['type']}' not in whitelist"
            )
```

- [ ] **Step 4：跑测试，确认通过**

```bash
python3 -m pytest tests/test_model_whitelist.py -v
```

预期：5 passed。

- [ ] **Step 5：Commit**

```bash
git add app/core/model_whitelist.py tests/test_model_whitelist.py
git commit -m "feat(core): add ModelWhitelist (dynamic OC registry scan)"
```

---

### Task 4.4：`app/core/dataset_whitelist.py`（DatasetWhitelist）

**Files:**
- Create: `opencompass-app/app/core/dataset_whitelist.py`
- Create: `opencompass-app/tests/test_dataset_whitelist.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_dataset_whitelist.py
import pytest
from app.core.dataset_whitelist import DatasetWhitelist


PROMPT_TYPE = "opencompass.openicl.icl_prompt_template.PromptTemplate"


def test_validate_missing_abbr():
    with pytest.raises(ValueError, match="missing 'abbr' field"):
        DatasetWhitelist.validate_dataset_item({})


def test_validate_unknown_dataset_type():
    with pytest.raises(ValueError, match="not in whitelist"):
        DatasetWhitelist.validate_dataset_item({
            "abbr": "x",
            "type": "opencompass.datasets.fake.FakeDataset",
            "path": "/data/opencompass/datasets/customer/x.jsonl",
        })


def test_validate_path_prefix():
    with pytest.raises(ValueError, match="must start with /data/opencompass/datasets/customer/"):
        DatasetWhitelist.validate_dataset_item({
            "abbr": "x",
            "type": "opencompass.datasets.jsonl.JsonlDataset",
            "path": "/tmp/wrong.jsonl",
        })


def test_validate_subtype_inferencer_rejected(monkeypatch):
    monkeypatch.setattr(DatasetWhitelist, "_DATASET", frozenset({"opencompass.datasets.jsonl.JsonlDataset"}))
    monkeypatch.setattr(DatasetWhitelist, "_INFER", frozenset({"good_infer"}))
    with pytest.raises(ValueError, match="infer_cfg.inferencer.type .* not in whitelist"):
        DatasetWhitelist.validate_dataset_item({
            "abbr": "x",
            "type": "opencompass.datasets.jsonl.JsonlDataset",
            "path": "/data/opencompass/datasets/customer/x.jsonl",
            "infer_cfg": {"inferencer": {"type": "bad_infer"}},
        })


def test_validate_subtype_prompt_template_accepted(monkeypatch):
    monkeypatch.setattr(DatasetWhitelist, "_DATASET", frozenset({"opencompass.datasets.jsonl.JsonlDataset"}))
    monkeypatch.setattr(DatasetWhitelist, "_PROMPT", frozenset({PROMPT_TYPE}))
    monkeypatch.setattr(DatasetWhitelist, "_RETRIEVER", frozenset({"r"}))
    monkeypatch.setattr(DatasetWhitelist, "_INFER", frozenset({"i"}))
    monkeypatch.setattr(DatasetWhitelist, "_EVAL", frozenset({"e"}))
    # 不应抛错
    DatasetWhitelist.validate_dataset_item({
        "abbr": "x",
        "type": "opencompass.datasets.jsonl.JsonlDataset",
        "path": "/data/opencompass/datasets/customer/x.jsonl",
        "infer_cfg": {"prompt_template": {"type": PROMPT_TYPE}},
    })


def test_validate_subtype_evaluator_rejected(monkeypatch):
    monkeypatch.setattr(DatasetWhitelist, "_DATASET", frozenset({"opencompass.datasets.jsonl.JsonlDataset"}))
    monkeypatch.setattr(DatasetWhitelist, "_PROMPT", frozenset({PROMPT_TYPE}))
    monkeypatch.setattr(DatasetWhitelist, "_RETRIEVER", frozenset({"r"}))
    monkeypatch.setattr(DatasetWhitelist, "_INFER", frozenset({"i"}))
    monkeypatch.setattr(DatasetWhitelist, "_EVAL", frozenset({"e"}))
    with pytest.raises(ValueError, match="eval_cfg.evaluator.type .* not in whitelist"):
        DatasetWhitelist.validate_dataset_item({
            "abbr": "x",
            "type": "opencompass.datasets.jsonl.JsonlDataset",
            "path": "/data/opencompass/datasets/customer/x.jsonl",
            "infer_cfg": {"prompt_template": {"type": PROMPT_TYPE}},
            "eval_cfg": {"evaluator": {"type": "bad_eval"}},
        })
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_dataset_whitelist.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写最小实现**

```python
# app/core/dataset_whitelist.py
"""数据集与子组件白名单。

覆盖 5 个 type 字段位置：
- dataset.type                                     （LOAD_DATASET 注册表）
- infer_cfg.prompt_template.type                   （硬编码 1 个）
- infer_cfg.retriever.type                         （手扫 icl_retriever 子包）
- infer_cfg.inferencer.type                        （ICL_INFERENCERS 注册表）
- eval_cfg.evaluator.type                          （ICL_EVALUATORS 注册表）
"""
import logging

log = logging.getLogger(__name__)

_PROMPT_TEMPLATE_TYPES = frozenset({
    "opencompass.openicl.icl_prompt_template.PromptTemplate",
})


def _scan_retriever_subclasses() -> frozenset[str]:
    """手扫 icl_retriever 子包下的 BaseRetriever 子类（OC 没有注册表机制）。"""
    try:
        import opencompass.openicl.icl_retriever as pkg
        from opencompass.openicl.icl_retriever.icl_base_retriever import BaseRetriever
        found: set[str] = set()
        for name in dir(pkg):
            obj = getattr(pkg, name)
            if isinstance(obj, type) and issubclass(obj, BaseRetriever) and obj is not BaseRetriever:
                found.add(f"{obj.__module__}.{obj.__name__}")
        return frozenset(found)
    except ImportError:
        return frozenset()


def _registry_keys(registry_obj) -> frozenset[str]:
    """从 mmengine Registry 实例中提取模块键。"""
    try:
        return frozenset(registry_obj._module_dict.keys())
    except AttributeError:
        return frozenset()


class DatasetWhitelist:
    _DATASET: frozenset[str] | None = None
    _PROMPT: frozenset[str] = _PROMPT_TEMPLATE_TYPES
    _RETRIEVER: frozenset[str] | None = None
    _INFER: frozenset[str] | None = None
    _EVAL: frozenset[str] | None = None

    @classmethod
    def dataset_types(cls) -> frozenset[str]:
        if cls._DATASET is None:
            try:
                from opencompass.registry import LOAD_DATASET
                cls._DATASET = _registry_keys(LOAD_DATASET)
            except ImportError:
                log.warning("opencompass not installed; dataset whitelist is empty")
                cls._DATASET = frozenset()
        return cls._DATASET

    @classmethod
    def prompt_template_types(cls) -> frozenset[str]:
        return cls._PROMPT

    @classmethod
    def retriever_types(cls) -> frozenset[str]:
        if cls._RETRIEVER is None:
            cls._RETRIEVER = _scan_retriever_subclasses()
        return cls._RETRIEVER

    @classmethod
    def inferencer_types(cls) -> frozenset[str]:
        if cls._INFER is None:
            try:
                from opencompass.registry import ICL_INFERENCERS
                cls._INFER = _registry_keys(ICL_INFERENCERS)
            except ImportError:
                cls._INFER = frozenset()
        return cls._INFER

    @classmethod
    def evaluator_types(cls) -> frozenset[str]:
        if cls._EVAL is None:
            try:
                from opencompass.registry import ICL_EVALUATORS
                cls._EVAL = _registry_keys(ICL_EVALUATORS)
            except ImportError:
                cls._EVAL = frozenset()
        return cls._EVAL

    @classmethod
    def validate_dataset_item(cls, ds: dict) -> None:
        if not isinstance(ds, dict):
            raise ValueError("dataset item must be a dict")
        if not ds.get("abbr"):
            raise ValueError("missing 'abbr' field")

        type_str = ds.get("type")
        if type_str not in cls.dataset_types():
            raise ValueError(f"dataset type '{type_str}' not in whitelist")

        path = ds.get("path", "")
        if not path.startswith("/data/opencompass/datasets/customer/"):
            raise ValueError(
                f"path must start with /data/opencompass/datasets/customer/, got: {path}"
            )

        cls._validate_subtype(ds, "infer_cfg", "prompt_template", cls.prompt_template_types())
        cls._validate_subtype(ds, "infer_cfg", "retriever", cls.retriever_types())
        cls._validate_subtype(ds, "infer_cfg", "inferencer", cls.inferencer_types())
        cls._validate_subtype(ds, "eval_cfg", "evaluator", cls.evaluator_types())

    @staticmethod
    def _validate_subtype(ds: dict, section: str, key: str, allowed: frozenset[str]) -> None:
        sub_type = (ds.get(section) or {}).get(key, {}).get("type")
        if sub_type and sub_type not in allowed:
            raise ValueError(f"{section}.{key}.type '{sub_type}' not in whitelist")
```

- [ ] **Step 4：跑测试，确认通过**

```bash
python3 -m pytest tests/test_dataset_whitelist.py -v
```

预期：6 passed。

- [ ] **Step 5：Commit**

```bash
git add app/core/dataset_whitelist.py tests/test_dataset_whitelist.py
git commit -m "feat(core): add DatasetWhitelist (5-field coverage)"
```

---

## 阶段 5：核心引擎

### Task 5.1：`app/oc_config/generator.py`（动态 config 拼装）+ 测试

**Files:**
- Create: `opencompass-app/app/oc_config/generator.py`
- Modify: `opencompass-app/app/core/dataset_registry.py`（暴露 `_load_with_path`）
- Create: `opencompass-app/tests/test_generator.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_generator.py
import asyncio
from pathlib import Path
from app.models.request import CreateJobRequest, DatasetItem, ModelItem
from app.oc_config.generator import generate_config


def test_builtin_dataset_renders_from_import(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text(
        "- gsm8k:\n    name: GSM8K\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.dataset_registry.DatasetRegistry._INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    req = CreateJobRequest(
        job_id="job_20260808_abc",
        datasets=[DatasetItem(abbr="gsm8k")],
        models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path="qwen", key="sk-test")],
    )
    path = asyncio.run(generate_config(req))
    assert Path(path).exists()
    text = Path(path).read_text(encoding="utf-8")
    assert "from opencompass.configs.datasets.gsm8k.gsm8k_gen import gsm8k_datasets" in text
    assert "with read_base():" in text
    assert "datasets = gsm8k_datasets" in text
    assert "models = [model_qwen_0]" in text


def test_custom_dataset_renders_inline(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text("- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n", encoding="utf-8")
    monkeypatch.setattr("app.core.dataset_registry.DatasetRegistry._INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    req = CreateJobRequest(
        job_id="job_20260808_abc",
        datasets=[DatasetItem(abbr="my_custom", type="opencompass.datasets.custom.CustomDataset", path="/data/opencompass/datasets/customer/my.jsonl", reader_cfg={"input_columns": ["question"]}, infer_cfg={"prompt_template": {"type": "PromptTemplate"}}, eval_cfg={"evaluator": {"type": "AccEvaluator"}})],
        models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path="qwen")],
    )
    path = asyncio.run(generate_config(req))
    text = Path(path).read_text(encoding="utf-8")
    assert "dataset_my_custom_0 = [" in text
    assert "models = [model_qwen_0]" in text
    assert '"type": "opencompass.datasets.custom.CustomDataset"' in text


def test_multi_dataset_concatenates_aliases(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text("- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n- mmlu:\n    configpath: opencompass/configs/datasets/mmlu/mmlu_gen.py\n", encoding="utf-8")
    monkeypatch.setattr("app.core.dataset_registry.DatasetRegistry._INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    req = CreateJobRequest(
        job_id="job_x",
        datasets=[DatasetItem(abbr="gsm8k"), DatasetItem(abbr="mmlu")],
        models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path="qwen")],
    )
    path = asyncio.run(generate_config(req))
    text = Path(path).read_text(encoding="utf-8")
    assert "datasets = gsm8k_datasets + mmlu_datasets" in text


def test_atomic_write_uses_replace(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text("- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n", encoding="utf-8")
    monkeypatch.setattr("app.core.dataset_registry.DatasetRegistry._INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    import app.oc_config.generator as gen_mod
    calls = []
    real_replace = gen_mod.os.replace
    def spy_replace(src, dst):
        calls.append((src, dst))
        real_replace(src, dst)
    monkeypatch.setattr(gen_mod.os, "replace", spy_replace)

    req = CreateJobRequest(job_id="job_atom", datasets=[DatasetItem(abbr="gsm8k")], models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path="qwen")])
    path = asyncio.run(generate_config(req))
    assert len(calls) == 1
    src, dst = calls[0]
    assert str(src).endswith(".py.tmp")
    assert str(dst).endswith("job_atom.py")


def test_rendered_file_lives_under_in_progress_dir(tmp_path, monkeypatch):
    fake_yaml = tmp_path / "fake_index.yaml"
    fake_yaml.write_text("- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n", encoding="utf-8")
    monkeypatch.setattr("app.core.dataset_registry.DatasetRegistry._INDEX", None)
    monkeypatch.setattr("app.core.dataset_registry._DATASET_INDEX_PATH", fake_yaml)
    monkeypatch.setenv("OC_DATA_ROOT", str(tmp_path / "oc-root"))

    req = CreateJobRequest(job_id="job_layout", datasets=[DatasetItem(abbr="gsm8k")], models=[ModelItem(type="opencompass.models.openai_api.OpenAISDK", path="qwen")])
    path = asyncio.run(generate_config(req))
    expected = Path(tmp_path) / "oc-root" / "workspace" / "_in_progress" / "job_layout" / "run_001" / "configs" / "job_layout.py"
    assert Path(path) == expected
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_generator.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：在 `app/core/dataset_registry.py` 暴露 `_load_with_path`（修改 Phase 4 产物）**

替换 `app/core/dataset_registry.py`：

```python
# app/core/dataset_registry.py
"""Dataset 注册表：从 dataset-index.yml 解析 abbr → (module_path, var_name)。"""
from pathlib import Path
import yaml


def _dataset_index_path() -> Path:
    """测试时可被 monkeypatch 替换。"""
    return Path(__file__).parent.parent / "data" / "dataset_index.yaml"


class DatasetRegistry:
    _INDEX: dict[str, tuple[str, str]] | None = None

    @classmethod
    def _load_with_path(cls, path: Path) -> dict[str, tuple[str, str]]:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or []
        idx = {}
        for entry in raw:
            (abbr, info), = entry.items()
            cfg_path = info["configpath"]
            module_path = cfg_path.removesuffix(".py").replace("/", ".")
            var_name = f"{Path(cfg_path).parent.name}_datasets"
            idx[abbr] = (module_path, var_name)
        return idx

    @classmethod
    def _load(cls) -> dict[str, tuple[str, str]]:
        if cls._INDEX is not None:
            return cls._INDEX
        cls._INDEX = cls._load_with_path(_dataset_index_path())
        return cls._INDEX

    @classmethod
    def is_builtin(cls, abbr: str) -> bool:
        return abbr in cls._load()

    @classmethod
    def resolve_builtin(cls, abbr: str) -> tuple[str, str]:
        idx = cls._load()
        if abbr not in idx:
            raise KeyError(f"dataset '{abbr}' not in registry")
        return idx[abbr]
```

- [ ] **Step 4：写 `app/oc_config/generator.py`**

```python
# app/oc_config/generator.py
"""OpenCompass config 动态拼装。

路径布局与设计文档 §6.10 一致：
    .../workspace/_in_progress/<job_id>/<run_dir>/configs/<job_id>.py
原子写：临时 .py.tmp → os.replace。
"""
import asyncio
import os
import pprint
from pathlib import Path

from app.core.dataset_registry import DatasetRegistry
from app.core.settings import get_settings
from app.models.request import CreateJobRequest


def _in_progress_dir(job_id: str, run_dir: str):
    return (
        Path(get_settings().oc_data_root)
        / "workspace"
        / "_in_progress"
        / job_id
        / run_dir
        / "configs"
    )


def _model_alias(path: str, idx: int) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in path)
    return f"model_{safe.lower()}_{idx}"


def _dataset_alias(abbr: str, idx: int) -> str:
    safe = "".join(
        ch if (ch.isalnum() or "\u4e00" <= ch <= "\u9fff") else "_" for ch in abbr
    )
    return f"dataset_{safe}_{idx}"


def _dump(obj) -> str:
    return pprint.pformat(obj, indent=4, width=88, sort_dicts=False)


def _render(
    dataset_imports, dataset_assigns, dataset_aliases,
    model_assigns, model_aliases,
) -> str:
    lines = ["# Auto-generated by opencompass-app", ""]
    lines.append("from mmengine.config import read_base")
    lines.append("")
    if dataset_imports:
        lines.append("# ===== Built-in datasets (from import) =====")
        lines.append("with read_base():")
        lines.extend(dataset_imports)
        lines.append("")
    if dataset_assigns:
        lines.append("# ===== Custom datasets (inline dict, type in whitelist) =====")
        lines.extend(dataset_assigns)
        lines.append("")
    lines.append(f"datasets = {' + '.join(dataset_aliases)}")
    lines.append("")
    lines.append("# ===== Models (inline dict, type in whitelist) =====")
    lines.extend(model_assigns)
    lines.append("")
    lines.append(f"models = [{', '.join(model_aliases)}]")
    return "\n".join(lines)


async def generate_config(req: CreateJobRequest, run_dir: str = "run_001") -> str:
    config_dir = _in_progress_dir(req.job_id, run_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{req.job_id}.py"

    dataset_imports: list[str] = []
    dataset_assigns: list[str] = []
    dataset_aliases: list[str] = []
    for idx, ds in enumerate(req.datasets):
        item = ds.model_dump()
        if set(item.keys()) <= {"abbr"}:
            mod, var = DatasetRegistry.resolve_builtin(item["abbr"])
            dataset_imports.append(f"    from {mod} import {var}")
            dataset_aliases.append(var)
        else:
            alias = _dataset_alias(item["abbr"], idx)
            dataset_assigns.append(f"{alias} = {_dump([item])}")
            dataset_aliases.append(alias)

    model_assigns: list[str] = []
    model_aliases: list[str] = []
    for idx, m in enumerate(req.models):
        alias = _model_alias(m.path, idx)
        model_assigns.append(f"{alias} = {_dump(m.model_dump())}")
        model_aliases.append(alias)

    source = _render(
        dataset_imports, dataset_assigns, dataset_aliases,
        model_assigns, model_aliases,
    )

    tmp = config_path.with_suffix(".py.tmp")
    tmp.write_text(source, encoding="utf-8")
    os.replace(tmp, config_path)
    return str(config_path)
```

- [ ] **Step 5：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_generator.py -v
```

预期：5 passed。

- [ ] **Step 6：Commit**

```bash
git add app/core/dataset_registry.py app/oc_config/generator.py tests/test_generator.py
git commit -m "feat(oc_config): add dynamic config generator with atomic write"
```

---

### Task 5.2：`app/executor/subprocess_runner.py`（subprocess 执行器）+ 测试

**Files:**
- Create: `opencompass-app/app/executor/subprocess_runner.py`
- Create: `opencompass-app/tests/test_subprocess_runner.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_subprocess_runner.py
import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.executor.subprocess_runner import start, wait_and_finalize
from app.stores.nfs_state import JobStateStore
from app.core.state import InstanceState


def test_start_constructs_correct_command(monkeypatch, tmp_path):
    captured = {}

    class FakeProc:
        pid = 12345

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    config_path = tmp_path / "workspace" / "_in_progress" / "job_x" / "run_001" / "configs" / "job_x.py"
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
        "job_id": "job_z", "status": "running", "instance_id": "i",
        "datasets": [], "models": [], "config_path": "/x", "work_dir": "/y",
        "created_at": "t", "started_at": "t", "finished_at": None,
        "exit_code": None, "error_message": None, "pid": 1, "created_by": None,
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
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_subprocess_runner.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写最小实现**

```python
# app/executor/subprocess_runner.py
"""OpenCompass subprocess 执行器。

参数布局（与设计文档 §6.11 / §8.1 一致）：
    config_path = .../<job_id>/<run_dir>/configs/<job_id>.py
    -w 指向    = .../<job_id>/
    -r 指向    = <run_dir>
"""
import asyncio
from pathlib import Path

from app.core.state import InstanceState
from app.stores.nfs_state import JobStateStore
from app.utils.time import now_iso


async def start(job_id: str, config_path: str) -> asyncio.subprocess.Process:
    config_p = Path(config_path)
    run_dir = config_p.parent.parent
    cmd = [
        "opencompass", config_path,
        "-w", str(run_dir.parent),
        "-r", run_dir.name,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    return proc


async def wait_and_finalize(
    job_id: str,
    proc: asyncio.subprocess.Process,
    state_store: JobStateStore,
    instance_state: InstanceState,
) -> None:
    rc = await proc.wait()
    current = state_store.read(job_id)
    if current is None:
        await instance_state.release(job_id)
        return

    final_status = "completed" if rc == 0 else "failed"
    state_store.write_atomic(job_id, {
        **current,
        "status": final_status,
        "finished_at": now_iso(),
        "exit_code": rc,
        "error_message": None if rc == 0 else f"opencompass exit {rc}",
    })
    await instance_state.release(job_id)
```

- [ ] **Step 4：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_subprocess_runner.py -v
```

预期：4 passed。

- [ ] **Step 5：Commit**

```bash
git add app/executor/subprocess_runner.py tests/test_subprocess_runner.py
git commit -m "feat(executor): add subprocess_runner with finalize-on-exit"
```

---

## 阶段 6：API 层

### Task 6.1：`app/api/workers.py` + 最小 `app/main.py` + 测试

**Files:**
- Create: `opencompass-app/app/api/workers.py`
- Create: `opencompass-app/app/main.py`（首版仅含 `/health` + `/workers/me/free`）
- Create: `opencompass-app/tests/test_workers_api.py`

- [ ] **Step 1：写失败测试 + 在 conftest.py 增加 client fixture**

修改 `tests/conftest.py` 增加 `client` fixture：

```python
# tests/conftest.py（追加 import + fixture）
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
```

写 `tests/test_workers_api.py`：

```python
# tests/test_workers_api.py
import asyncio

from app.main import create_app, instance_state, state_store


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
    assert body["max"] == instance_state.max_concurrent


def test_workers_me_free_after_acquire(client):
    asyncio.run(instance_state.try_acquire("job_a"))
    res = client.get("/api/v1/workers/me/free")
    body = res.json()
    assert body["running"] == 1
    assert body["available"] == body["max"] - 1


def test_health_degraded_when_nfs_state_fails(client, monkeypatch):
    def boom():
        raise OSError("disk gone")
    monkeypatch.setattr(state_store, "list_ids", boom)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "degraded"
    assert body["checks"]["nfs_state"].startswith("fail")
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_workers_api.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3：写 `app/api/workers.py`**

```python
# app/api/workers.py
"""Worker 池查询 / 健康检查。"""
import shutil

from fastapi import APIRouter

from app.main import get_instance_state, get_state_store
from app.models.response import FreeWorkerCount, HealthCheck


router = APIRouter(prefix="/api/v1/workers", tags=["workers"])
health_router = APIRouter(tags=["health"])


@router.get("/me/free", response_model=FreeWorkerCount)
async def free_workers() -> FreeWorkerCount:
    s = get_instance_state()
    return FreeWorkerCount(
        available=s.available_slots(),
        max=s.max_concurrent,
        running=s.running_count(),
    )


@health_router.get("/health", response_model=HealthCheck)
async def health() -> HealthCheck:
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

- [ ] **Step 4：写最小 `app/main.py`**

```python
# app/main.py
"""FastAPI 入口。"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.workers import router as workers_router, health_router
from app.core.settings import Settings
from app.core.state import InstanceState
from app.stores.nfs_state import JobStateStore


state_store: JobStateStore | None = None
instance_state: InstanceState | None = None


def get_state_store() -> JobStateStore:
    if state_store is None:
        raise RuntimeError("state_store not initialized; check lifespan")
    return state_store


def get_instance_state() -> InstanceState:
    if instance_state is None:
        raise RuntimeError("instance_state not initialized; check lifespan")
    return instance_state


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
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="opencompass-app", lifespan=lifespan)
    app.include_router(workers_router)
    app.include_router(health_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        reload=False,
    )
```

- [ ] **Step 5：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_workers_api.py -v
```

预期：4 passed。

- [ ] **Step 6：Commit**

```bash
git add app/api/workers.py app/main.py tests/test_workers_api.py tests/conftest.py
git commit -m "feat(api): add /workers/me/free and /health endpoints"
```

---

### Task 6.2：`app/api/jobs.py` + 完整 `app/main.py` + 测试

**Files:**
- Create: `opencompass-app/app/api/jobs.py`
- Modify: `opencompass-app/app/main.py`（注册 jobs_router）
- Create: `opencompass-app/tests/test_jobs_api.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_jobs_api.py
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.dataset_registry import DatasetRegistry
from app.core.dataset_whitelist import DatasetWhitelist
from app.core.model_whitelist import ModelWhitelist
from app.main import create_app


@pytest.fixture
def fake_yaml(tmp_path):
    p = tmp_path / "di.yaml"
    p.write_text("- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n", encoding="utf-8")
    return p


@pytest.fixture
def client(fake_yaml, monkeypatch):
    monkeypatch.setattr(DatasetRegistry, "_INDEX", None)
    DatasetRegistry._INDEX = DatasetRegistry._load_with_path(fake_yaml)
    monkeypatch.setattr(ModelWhitelist, "_TYPES", frozenset({"opencompass.models.openai_api.OpenAISDK"}))
    monkeypatch.setattr(DatasetWhitelist, "_DATASET", frozenset({"opencompass.datasets.custom.CustomDataset"}))
    monkeypatch.setattr(DatasetWhitelist, "_EVAL", frozenset({"AccEvaluator"}))
    monkeypatch.setattr(DatasetWhitelist, "_INFER", frozenset({"GenInferencer"}))
    monkeypatch.setattr(DatasetWhitelist, "_RETRIEVER", frozenset({"ZeroRetriever"}))

    import app.executor.subprocess_runner as sr
    async def fake_start(job_id, config_path):
        proc = AsyncMock()
        proc.pid = 99999
        proc.wait = AsyncMock(return_value=0)
        return proc
    monkeypatch.setattr(sr, "start", fake_start)

    app = create_app()
    with TestClient(app) as c:
        yield c

    monkeypatch.setattr(DatasetRegistry, "_INDEX", None)


def test_post_jobs_201_with_builtin_dataset(client):
    req = {
        "job_id": "job_20260808_abc",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{
            "type": "opencompass.models.openai_api.OpenAISDK",
            "path": "qwen", "key": "sk-test",
        }],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "running"
    assert body["job_id"] == "job_20260808_abc"


def test_post_jobs_409_when_duplicate(client):
    req = {
        "job_id": "job_dup",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    res1 = client.post("/api/v1/jobs", json=req)
    assert res1.status_code == 201
    res2 = client.post("/api/v1/jobs", json=req)
    assert res2.status_code == 409


def test_post_jobs_422_unknown_builtin(client):
    req = {
        "job_id": "job_z",
        "datasets": [{"abbr": "definitely_not_a_real_dataset_xyzzy"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 422


def test_post_jobs_422_when_model_type_not_in_whitelist(client):
    req = {
        "job_id": "job_w",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "not.In.Whitelist", "path": "qwen"}],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 422


def test_get_job_200_after_create(client):
    req = {
        "job_id": "job_get_200",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    client.post("/api/v1/jobs", json=req)
    res = client.get("/api/v1/jobs/job_get_200")
    assert res.status_code == 200
    body = res.json()
    assert body["job_id"] == "job_get_200"
    assert body["status"] in ("running", "completed")


def test_get_job_404(client):
    res = client.get("/api/v1/jobs/no_such_job_id_xyz")
    assert res.status_code == 404


def test_post_jobs_503_when_at_capacity(client, monkeypatch):
    from app.main import instance_state as inst
    for i in range(inst.max_concurrent):
        asyncio.run(inst.try_acquire(f"slot_{i}"))
    req = {
        "job_id": "job_overflow",
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen"}],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 503
```

- [ ] **Step 2：跑测试，确认失败**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_api.py -v
```

预期：`ModuleNotFoundError` 或 404/405。

- [ ] **Step 3：写 `app/api/jobs.py`**

```python
# app/api/jobs.py
"""任务创建 + 查询。"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.dataset_registry import DatasetRegistry
from app.core.dataset_whitelist import DatasetWhitelist
from app.core.model_whitelist import ModelWhitelist
from app.executor import subprocess_runner
from app.main import get_instance_state, get_state_store
from app.models.enums import JobStatus
from app.models.request import CreateJobRequest
from app.models.response import JobResponse
from app.oc_config.generator import generate_config
from app.utils.ids import is_valid_job_id
from app.utils.time import now_iso


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _validate_request(req: CreateJobRequest) -> None:
    if not is_valid_job_id(req.job_id):
        raise HTTPException(422, f"invalid job_id format: {req.job_id}")

    for ds in req.datasets:
        if set(ds.model_dump().keys()) <= {"abbr"}:
            if not DatasetRegistry.is_builtin(ds.abbr):
                raise HTTPException(422, f"unknown builtin dataset: {ds.abbr}")
        else:
            try:
                DatasetWhitelist.validate_dataset_item(ds.model_dump())
            except ValueError as e:
                raise HTTPException(422, str(e))

    for m in req.models:
        try:
            ModelWhitelist.validate(m.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e))


@router.post("", status_code=201, response_model=JobResponse)
async def create_job(req: CreateJobRequest) -> JobResponse:
    store = get_state_store()
    inst = get_instance_state()

    _validate_request(req)

    if store.exists(req.job_id):
        raise HTTPException(409, f"job_id exists: {req.job_id}")
    if inst.is_at_capacity():
        raise HTTPException(503, "worker pool at capacity")

    if not await inst.try_acquire(req.job_id):
        raise HTTPException(503, "worker pool at capacity")

    try:
        config_path = await generate_config(req)
    except Exception as e:
        await inst.release(req.job_id)
        raise HTTPException(500, f"generate_config failed: {e}")

    work_dir = str(Path(config_path).parent.parent)

    initial = {
        "job_id": req.job_id,
        "status": JobStatus.STARTING.value,
        "instance_id": inst.instance_id,
        "datasets": [ds.model_dump() for ds in req.datasets],
        "models": [m.model_dump() for m in req.models],
        "config_path": config_path,
        "work_dir": work_dir,
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "error_message": None,
        "pid": None,
        "created_by": req.created_by,
    }
    store.write_atomic(req.job_id, initial)

    try:
        proc = await subprocess_runner.start(req.job_id, config_path)
    except Exception as e:
        await inst.release(req.job_id)
        store.write_atomic(req.job_id, {
            **initial,
            "status": JobStatus.FAILED.value,
            "finished_at": now_iso(),
            "error_message": f"subprocess start failed: {e}",
        })
        raise HTTPException(500, f"subprocess start failed: {e}")

    inst.track_process(req.job_id, proc)
    store.write_atomic(req.job_id, {
        **initial,
        "status": JobStatus.RUNNING.value,
        "started_at": now_iso(),
        "pid": proc.pid,
    })

    # 异步终态化（不阻塞响应）
    asyncio.create_task(
        subprocess_runner.wait_and_finalize(req.job_id, proc, store, inst)
    )

    final_state = store.read(req.job_id) or initial
    return JobResponse(**final_state)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    state = get_state_store().read(job_id)
    if state is None:
        raise HTTPException(404, "job not found")
    return JobResponse(**state)
```

- [ ] **Step 4：在 `app/main.py` 中注册 jobs_router**

修改 `app/main.py`：

```python
# app/main.py（在 import 区追加）
from app.api.jobs import router as jobs_router

# create_app 内追加
def create_app() -> FastAPI:
    app = FastAPI(title="opencompass-app", lifespan=lifespan)
    app.include_router(workers_router)
    app.include_router(health_router)
    app.include_router(jobs_router)
    return app
```

- [ ] **Step 5：跑测试，确认通过**

```bash
cd opencompass-app
python3 -m pytest tests/test_jobs_api.py -v
```

预期：7 passed。

- [ ] **Step 6：Commit**

```bash
git add app/api/jobs.py app/main.py tests/test_jobs_api.py
git commit -m "feat(api): add POST /jobs and GET /jobs/{id} with full validation"
```

---

## 阶段 7：联调与文档

### Task 7.1：手动 uvicorn 集成测试（smoke）

- [ ] **Step 1：安装运行依赖**

```bash
cd opencompass-app
python3 -m pip install -r requirements.txt
python3 -m pip install pytest pytest-asyncio httpx ruff
```

- [ ] **Step 2：跑全套测试**

```bash
cd opencompass-app
python3 -m pytest tests/ -v
```

预期：所有用例通过。

- [ ] **Step 3：启动 uvicorn（前台阻塞）**

```bash
cd opencompass-app
PORT=8080 INSTANCE_ID=local-dev OC_DATA_ROOT=/tmp/opencompass-dev \
    python3 -m app.main
```

另开终端走下列 curl：

- [ ] **Step 4：健康检查**

```bash
curl -sS http://localhost:8080/health | python3 -m json.tool
```

预期：

```json
{
  "status": "healthy",
  "checks": {"nfs_state": "ok", "opencompass_binary": "ok"}
}
```

- [ ] **Step 5：提交一个 builtin dataset job**

```bash
curl -sS -X POST http://localhost:8080/api/v1/jobs \
    -H 'content-type: application/json' \
    -d '{
      "job_id": "smoke_001",
      "datasets": [{"abbr": "gsm8k"}],
      "models": [{
        "type": "opencompass.models.openai_api.OpenAISDK",
        "path": "qwen",
        "key": "EMPTY"
      }]
    }' | python3 -m json.tool
```

预期：`201`，`status: "running"`。

- [ ] **Step 6：查询任务状态**

```bash
sleep 1
curl -sS http://localhost:8080/api/v1/jobs/smoke_001 | python3 -m json.tool
```

预期：`200`。

- [ ] **Step 7：worker 池查询**

```bash
curl -sS http://localhost:8080/api/v1/workers/me/free | python3 -m json.tool
```

预期：返回 `{available, max, running}`。

- [ ] **Step 8：核对 config 文件**

```bash
cat /tmp/opencompass-dev/workspace/_in_progress/smoke_001/run_001/configs/smoke_001.py
```

预期：含 `from opencompass.configs.datasets.gsm8k.gsm8k_gen import gsm8k_datasets`、`datasets = gsm8k_datasets`、`models = [model_qwen_0]`。

- [ ] **Step 9：确认无源码修改**

```bash
cd ..
git diff opencompass/ | head
git status opencompass/
```

预期：`opencompass/` 仍 `clean`。

---

### Task 7.2：`README.md`

**Files:**
- Create: `opencompass-app/README.md`

- [ ] **Step 1：写 README.md**

```markdown
# opencompass-app

OpenCompass 评测任务的最小调度服务（FastAPI）。本服务**不**修改 OpenCompass 源码，
仅通过 `subprocess` + 动态生成的 config 文件调用 OC CLI。

## 范围

MVP 闭环覆盖 4 个端点：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/jobs` | POST | 创建并启动一个评测任务 |
| `/api/v1/jobs/{job_id}` | GET | 查询任务状态 |
| `/api/v1/workers/me/free` | GET | 当前实例空闲 worker 数 |
| `/health` | GET | 健康检查 |

不在 MVP 范围内：`POST /stop`、`DELETE`、`GET /jobs` 列表、`recover_after_restart`、
`PATCH /workers/me/capacity`。

## 架构图

```
HTTP Client → FastAPI → opencompass subprocess
                ↓
        NFS JSON 状态文件（原子写）
```

完整设计：[`docs/opencompass-scheduler-design.md`](../../docs/opencompass-scheduler-design.md)
MVP 设计：[`docs/superpowers/specs/2026-08-09-opencompass-app-mvp-design.md`](../../docs/superpowers/specs/2026-08-09-opencompass-app-mvp-design.md)

## 目录结构

```
app/
├── main.py                     # FastAPI 入口
├── api/                        # 路由层
│   ├── jobs.py
│   └── workers.py
├── core/                       # 业务核心
│   ├── dataset_registry.py     # dataset-index.yml 查表
│   ├── dataset_whitelist.py    # 数据集/子类型白名单
│   ├── model_whitelist.py      # 模型白名单（BaseAPIModel 子类扫描）
│   ├── settings.py             # pydantic-settings
│   ├── instance.py             # INSTANCE_ID 派生
│   └── state.py                # InstanceState（worker 池）
├── oc_config/
│   └── generator.py            # mmengine read_base + inline dict
├── executor/
│   └── subprocess_runner.py    # opencompass CLI 子进程
├── stores/
│   └── nfs_state.py            # 原子 JSON 持久化
├── models/                     # Pydantic 数据模型
├── data/
│   └── dataset_index.yaml      # 复制自 ../../dataset-index.yml
└── utils/
    ├── ids.py
    └── time.py
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `INSTANCE_ID` | `hostname:port` 自动派生 | 实例唯一标识 |
| `OC_DATA_ROOT` | `/data/opencompass` | 工作区根目录 |
| `MAX_CONCURRENT` | `8` | 每实例并发上限 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `PORT` | `8080` | uvicorn 端口 |

## 本地开发

```bash
# 安装运行 + 开发依赖
python3 -m pip install -r requirements.txt
python3 -m pip install pytest pytest-asyncio httpx ruff

# 跑测试
cd opencompass-app
python3 -m pytest tests/ -v

# 启动服务（开发实例）
PORT=8080 INSTANCE_ID=local-dev \
    OC_DATA_ROOT=/tmp/opencompass-dev \
    python3 -m app.main

# 提交一个任务
curl -X POST http://localhost:8080/api/v1/jobs \
    -H 'content-type: application/json' \
    -d '{
      "job_id": "smoke_001",
      "datasets": [{"abbr": "gsm8k"}],
      "models": [{
        "type": "opencompass.models.openai_api.OpenAISDK",
        "path": "qwen",
        "key": "EMPTY"
      }]
    }'
```

## 关键约束

- **黑盒集成**：禁止修改 `opencompass/` 目录下任何文件。
- **白名单动态扫描**：所有模型 / 数据集 / 评估器白名单均通过扫描 OC 注册表获得，
  禁止硬编码类名字符串。
- **原子状态写**：所有 NFS 任务状态文件通过 `tempfile + fsync + os.replace` 写入。

## 测试策略

- 单元测试：utils、whitelists、registry、generator、subprocess_runner
- API 集成测试：`FastAPI.TestClient` + `monkeypatch` 桩掉 `subprocess_runner.start`
- 端到端：手动 `uvicorn` + `curl` 走通（见实施计划 `Phase 7.1`）
```

- [ ] **Step 2：Commit**

```bash
git add opencompass-app/README.md
git commit -m "docs(app): add README for opencompass-app MVP"
```

---

### Task 7.3：最终验证

- [ ] **Step 1：ruff 全量静态检查**

```bash
cd opencompass-app
ruff check app/ tests/
```

预期：`All checks passed!`

- [ ] **Step 2：完整测试套件**

```bash
cd opencompass-app
python3 -m pytest tests/ -v --tb=short
```

预期：≥30 用例通过。

- [ ] **Step 3：黑盒集成约束校验**

```bash
cd ..
git diff --stat opencompass/ 2>&1
git diff opencompass/ 2>&1 | wc -l
```

预期：`0 0` 或极空输出。

- [ ] **Step 4：完成定义（Definition of Done）**

逐条对照 spec §11：

- [ ] `pytest tests/ -v` 全部通过
- [ ] `python -m app.main` 启动后 `curl /health` 返回 200
- [ ] `curl POST /api/v1/jobs` 能生成 config 并返回 201
- [ ] `curl GET /api/v1/jobs/{job_id}` 能读到状态
- [ ] `curl GET /api/v1/workers/me/free` 返回三段计数
- [ ] README.md 含本地开发指引
- [ ] 代码 `ruff check` 通过
- [ ] `opencompass/` 目录 `git diff` 为空

全部勾选后，MVP 闭环完成。

- [ ] **Step 5：Phase 7 commit（如有 README/lint 修复）**

```bash
git add opencompass-app/
git commit -m "chore(app): final MVP verification"
```

---

## 实施总结

| 阶段 | 任务数 | 估算代码行（含测试） |
|------|--------|---------------------|
| 1 脚手架 | 4 | ~50 |
| 2 工具/枚举/数据模型 | 4 | ~150 |
| 3 持久化/并发/配置 | 3 | ~250 |
| 4 注册表/白名单 | 4 | ~250 |
| 5 核心引擎 | 2 | ~250 |
| 6 API 层 | 2 | ~350 |
| 7 联调与文档 | 3 | ~100 |
| **合计** | **22** | **≈1400** |

---

## 自检结果（writing-plans self-review）

**1. Spec coverage**（spec §X → 本 plan Task Y）

- §1.1 目标 ✅ → Task 6.2 POST /jobs + Task 5.1 config 生成
- §3 目录结构 ✅ → Task 1.1
- §4 依赖 ✅ → Task 1.2/1.3
- §5.1 JobStatus ✅ → Task 2.1
- §5.2 Request/Response ✅ → Task 2.4
- §5.3 NFS JSON Schema ✅ → Task 3.1 + 3.2
- §6.1 ids.py ✅ → Task 2.2
- §6.2 time.py ✅ → Task 2.3
- §6.3 settings.py ✅ → Task 3.3
- §6.5 JobStateStore ✅ → Task 3.1
- §6.6 InstanceState ✅ → Task 3.2
- §6.7 DatasetRegistry ✅ → Task 4.2（Task 5.1 Step 3 强化 `_load_with_path`）
- §6.8 ModelWhitelist ✅ → Task 4.3
- §6.9 DatasetWhitelist ✅ → Task 4.4
- §6.10 generator ✅ → Task 5.1
- §6.11 subprocess_runner ✅ → Task 5.2
- §6.12 jobs.py ✅ → Task 6.2
- §6.13 workers.py ✅ → Task 6.1
- §6.14 main.py ✅ → Task 6.1 + 6.2
- §7 API 契约 ✅ → Task 6.1 + 6.2
- §8 POST /jobs 流程 ✅ → Task 6.2（11 步 inline 在 `create_job`）
- §9 测试设计 ✅ → 各 Task 的 Step 1 测试代码
- §10 实施顺序 ✅ → 本 plan 阶段 1-7
- §11 DoD ✅ → Task 7.3 Step 4
- §12 风险与缓解 ✅ → 散落在各 Task 的处理（如 `_dataset_alias` 中文字符支持）

**2. Placeholder scan**

- 无 `TBD` / `TODO` / `implement later` / `fill in details`
- 所有 Task 的 Step 1 包含完整可运行测试代码
- 所有 Task 的 Step 3/4 包含完整可运行实现代码
- 无 "类似 Task N" 偷懒引用

**3. Type consistency**（同名类型/方法签名一致性）

- `JobStateStore.write_atomic/read/exists/list_ids` 在 Task 3.1 定义，全文使用一致
- `InstanceState.try_acquire/release/track_process/running_count/available_slots/is_at_capacity/max_concurrent/instance_id` 在 Task 3.2/3.3 定义，全文使用一致
- `JobStatus.STARTING/RUNNING/FINALIZING/COMPLETED/FAILED` 在 Task 2.1 定义，全文使用一致
- `CreateJobRequest/DatasetItem/ModelItem/JobResponse/FreeWorkerCount/HealthCheck` 在 Task 2.4 定义，全文使用一致
- `is_valid_job_id/now_iso` 在 Task 2.2/2.3 定义，全文使用一致
- `generate_config(req, run_dir="run_001") -> str` 在 Task 5.1 定义，全文使用一致
- `subprocess_runner.start/wait_and_finalize` 在 Task 5.2 定义，全文使用一致
- `DatasetRegistry.is_builtin/resolve_builtin/_load_with_path` 在 Task 4.2/5.1 定义，全文使用一致
- `ModelWhitelist.validate/types` 在 Task 4.3 定义，全文使用一致
- `DatasetWhitelist.validate_dataset_item/{dataset,evaluator,inferencer,retriever,prompt_template}_types` 在 Task 4.4 定义，全文使用一致

**结论**：spec 全部要求覆盖；无 placeholder；类型/方法签名一致。

---

## 执行 handoff

Plan 已写入 [`docs/superpowers/plans/2026-08-09-opencompass-app-mvp.md`](../plans/2026-08-09-opencompass-app-mvp.md)，共 22 个 Task。

**两个执行选项：**

1. **Subagent-Driven（推荐）** —— 每个 Task 派一个独立 subagent 执行，task 间人工 review，快速迭代。
2. **Inline Execution** —— 在当前 session 中按 executing-plans 批量执行，阶段性 checkpoint 复审。
```

---