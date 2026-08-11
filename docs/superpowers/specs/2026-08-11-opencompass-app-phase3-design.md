# OpenCompass App Phase 3 设计：recover_after_restart + PATCH /workers/me/capacity

| 项目 | 内容 |
|------|------|
| 文档版本 | v1.0 |
| 编制日期 | 2026-08-11 |
| 适用范围 | OpenCompass 评测调度服务（FastAPI 实例） |
| 关联 PRD | [`opencompass-scheduler-prd.md`](../../opencompass-scheduler-prd.md) 第 5.3、5.6 节 |
| 关联技术设计 | [`opencompass-scheduler-design.md`](../../opencompass-scheduler-design.md) 第 5.3.4、5.4.3 节 |
| 文档状态 | 已批准，进入实现阶段 |

## 1. 背景与目标

PRD 第一轮范围内包含两项 MVP 后的关键运维能力，但被推迟到 Phase 3：

| 能力 | 来源 | 当前缺失 |
|------|------|---------|
| 实例崩溃后任务自动收尾 | PRD FR-6.1~6.6、AC-R-1~3 | 完全未实现 |
| 动态调整并发上限 | PRD FR-3.3、7.2 | 端点不存在，capacity 仅来自启动环境变量 |

**本设计目标**：在不破坏现有架构的前提下，补齐这两个运维能力，使实例具备基本的"故障自愈"和"运维时容量可调"。

## 2. 范围

### 2.1 包含

1. **recover_after_restart()**：lifespan startup 中扫描 NFS 残留状态并收尾
2. **`ready` 标志位**：recover 完成前 `/health` 返回 503
3. **`PATCH /api/v1/workers/me/capacity`**：调整 `max_concurrent`
4. **新增 Pydantic 模型** `CapacityAdjustRequest`
5. **完整测试覆盖**：单元 + 集成 + 冒烟脚本扩展

### 2.2 不包含（推迟到后续 Phase）

| 功能 | 推迟原因 |
|------|---------|
| finalizing 状态重跑 summarizer | MVP 未实现独立 summarizer 模块；本轮仅标记 failed |
| capacity 持久化（写 NFS JSON） | MVP 阶段重启次数少，环境变量回退可接受 |
| capacity 调整的硬上限（如 1024） | 运维场景有限，PRD 无明确要求 |
| 周期后台 recover 扫描 | 启动一次性扫描已满足 AC-R-1~3 |
| 进程 start_time 记录（防 PID 复用） | `os.kill(pid, 0)` 在 lifespan startup 串行执行窗口期已足够 |
| 调度生效（scheduled apply_time） | 立即生效满足运维诉求 |
| PATCH 预留扩展字段 | 当前仅 `max_concurrent` |

## 3. 架构概览

```
┌────────────────────────────────────────────────────────────────┐
│                     FastAPI 实例启动 (lifespan)                  │
└────────────┬───────────────────────────────────────────────────┘
             │
             ▼
   ┌──────────────────────────┐
   │ recover_after_restart()  │ ← 新模块 app/utils/recovery.py
   │  · list_all() 扫描       │
   │  · instance_id 过滤       │
   │  · 状态分支处理          │
   │  · 计数对齐              │
   └──────────┬───────────────┘
              │ 完成
              ▼
   ┌──────────────────────────┐
   │ instance_state.ready=True│
   └──────────┬───────────────┘
              │
              ▼
   ┌──────────────────────────┐         ┌──────────────────────────┐
   │ PATCH /me/capacity       │         │ /health 200 ready=True   │
   │  · max_concurrent        │ ──────► │ /health 503 ready=False  │
   │    >= running_count      │         └──────────────────────────┘
   │  · 立即写 InstanceState  │
   └──────────────────────────┘
```

## 4. 模块设计

### 4.1 新建 `app/utils/recovery.py`

```python
# app/utils/recovery.py
import logging
import os
from typing import Optional

from app.core.state import InstanceState
from app.models.enums import JobStatus
from app.stores.nfs_state import JobStateStore
from app.utils.time import now_iso

log = logging.getLogger(__name__)

STARTING = JobStatus.STARTING.value
RUNNING = JobStatus.RUNNING.value
CANCELLING = JobStatus.CANCELLING.value
FINALIZING = JobStatus.FINALIZING.value
FAILED = JobStatus.FAILED.value


def is_pid_in_current_session(pid: Optional[int]) -> bool:
    """检查 PID 是否属于当前进程会话（os.kill 信号 0 检查存在性）。"""
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
    """实例启动时扫描遗留任务并收尾。

    处理规则（按 PRD FR-6）：
      - starting        → failed（实例在启动子进程前崩溃）
      - running         → PID 不在新会话 → failed
      - cancelling      → PID 不在新会话 → failed
      - finalizing      → failed（不重跑 summarizer，PRD 推迟）
      - terminal        → 跳过
    """
    for job_id, state in store.list_all():
        if state.get("instance_id") != instance.instance_id:
            continue  # 别人的任务不归我管

        status = state.get("status")
        if status in (FAILED, JobStatus.COMPLETED.value, JobStatus.CANCELLED.value):
            continue  # 终态无需处理

        if status == STARTING:
            _mark_failed(store, instance, job_id, state,
                         "Instance crashed before subprocess started")
        elif status in (RUNNING, CANCELLING):
            pid = state.get("pid")
            if not is_pid_in_current_session(pid):
                _mark_failed(store, instance, job_id, state,
                             f"Instance crashed; PID {pid} not in current session")
            else:
                log.warning("Job %s PID %s still alive after restart; leaving for ops",
                            job_id, pid)
        elif status == FINALIZING:
            _mark_failed(store, instance, job_id, state,
                         "Instance crashed during finalization")
        else:
            log.warning("Unknown status %s for job %s; skipping", status, job_id)


def _mark_failed(store, instance, job_id, current, error_message):
    """标记任务为 failed 并对齐 slot 计数。"""
    new_state = {
        **current,
        "status": FAILED,
        "finished_at": now_iso(),
        "error_message": error_message,
    }
    store.write_atomic(job_id, new_state)
    # 计数对齐：reserve + release 让 in-memory _running 不残留
    instance.reserve_for_recovery(job_id)
    instance.release(job_id)
    log.info("Recovered job %s: %s", job_id, error_message)
```

### 4.2 修改 `app/core/state.py`

新增 `ready` 标志位 + recovery 用临时占位方法：

```python
class InstanceState:
    def __init__(self, max_concurrent: int, instance_id: str):
        # ... 既有字段 ...
        self.ready: bool = False    # 新增：recover 完成才 True

    def mark_ready(self) -> None:
        self.ready = True

    def reserve_for_recovery(self, job_id: str) -> None:
        """recover 时占位对齐计数（不参与并发限流判断路径）。"""
        self._running.add(job_id)
```

> **设计取舍**：`reserve_for_recovery` 是同步方法（与 `release` 同样），绕过锁。在 lifespan startup 单线程上下文安全。

### 4.3 修改 `app/main.py`

在 lifespan startup 中调用 recover：

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

    # 新增：recover 阻塞直到完成
    from app.utils.recovery import recover_after_restart
    await recover_after_restart(state_store, instance_state)
    instance_state.mark_ready()

    yield
```

### 4.4 修改 `app/api/workers.py`

#### 4.4.1 `/health` 加 ready 检查

```python
@router.get("/health")
async def health():
    from app.main import get_instance_state
    inst = get_instance_state()
    if not inst.ready:
        raise HTTPException(503, "Instance recovering after restart")
    # ... 既有检查 ...
```

#### 4.4.2 新增 `PATCH /me/capacity`

```python
@router.patch("/me/capacity")
async def adjust_capacity(req: CapacityAdjustRequest):
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

### 4.5 新建 `app/models/request.py`（如不存在）

```python
from pydantic import BaseModel, Field


class CapacityAdjustRequest(BaseModel):
    max_concurrent: int = Field(gt=0, description="New max concurrent jobs; must be > 0")
```

## 5. 端点契约

### 5.1 `PATCH /api/v1/workers/me/capacity`

| 维度 | 内容 |
|------|------|
| 方法 | PATCH |
| 路径 | `/api/v1/workers/me/capacity` |
| Content-Type | application/json |
| 请求体 | `{"max_concurrent": int > 0}` |
| 200 OK | `{"max_concurrent": int}` |
| 409 Conflict | `{"detail": "New max (N) less than current running (M)"}` |
| 422 Unprocessable | Pydantic 校验：`max_concurrent <= 0` 或字段缺失 |
| 503 Unavailable | 实例 recover 未完成 |

### 5.2 `/health`（修改）

- **未 ready**：返回 503 `{"detail": "Instance recovering after restart"}`
- **ready + 既有检查全 OK**：返回 200
- **ready + 任意检查失败**：返回 503

## 6. 数据契约

### 6.1 状态文件修改

recover 仅修改既有状态文件的 `status` / `finished_at` / `error_message` 字段，**不新增字段**。因此不引入新的数据迁移成本。

### 6.2 字段约束

| 字段 | 类型 | recover 后值 |
|------|------|------------|
| `status` | enum | 必为 `failed` |
| `finished_at` | ISO8601 | recover 时刻 |
| `error_message` | str | 见 §4.1 各分支文案 |

## 7. 错误处理

| 场景 | 处理 | 关键点 |
|------|------|--------|
| recover: PID 校验抛 OSError | 视为进程不存在 → failed | `os.kill` 自身可能抛异常 |
| recover: 状态文件损坏 | log warning + 跳过 | `list_all()` 已实现 |
| recover: write_atomic 失败 | log error + 跳过 | 单文件失败不阻断整个 recover |
| recover: 启动期 OOM | propagate → 进程退出 | K8s 重启 |
| PATCH: max_concurrent <= 0 | Pydantic 422 | `Field(gt=0)` 自动校验 |
| PATCH: max_concurrent < running | 业务校验 | 409 + 详细文案 |
| PATCH: 实例未 ready | 503 | 与 /health 一致 |
| /health: 未 ready | 503 | K8s liveness 用 |

## 8. 测试策略

### 8.1 单元测试

```
tests/test_recovery.py（新建）
  test_is_pid_in_current_session_returns_true_for_alive
  test_is_pid_in_current_session_returns_false_for_missing
  test_is_pid_in_current_session_returns_false_for_none
  test_recover_no_state_files
  test_recover_skips_other_instances
  test_recover_starting_marks_failed
  test_recover_running_marks_failed_when_pid_missing
  test_recover_running_warns_when_pid_alive
  test_recover_cancelling_marks_failed_when_pid_missing
  test_recover_finalizing_marks_failed
  test_recover_terminal_states_unchanged
  test_recover_corrupt_file_skipped
  test_recover_sets_ready_after_completion
  test_recover_aligns_slot_count

tests/test_workers_api.py（修改）
  test_patch_capacity_success_returns_new_value
  test_patch_capacity_below_running_returns_409
  test_patch_capacity_zero_returns_422
  test_patch_capacity_negative_returns_422
  test_patch_capacity_missing_field_returns_422
  test_patch_capacity_unavailable_during_recovery
  test_health_503_during_recovery
  test_health_200_after_ready

tests/test_state.py（修改）
  test_instance_state_ready_default_false
  test_instance_state_mark_ready_idempotent
  test_reserve_for_recovery_aligns_count
```

### 8.2 集成测试

```
tests/test_recovery_integration.py（新建）
  test_full_recovery_flow_startup_to_health_ready
  test_residual_tasks_marked_failed_on_restart
  test_recovery_continues_after_corrupt_file
```

### 8.3 冒烟脚本扩展

`scripts/smoke_manual.sh` 新增 4 项：

```
t14: PATCH /me/capacity 200 + 校验 free 立即变化
t15: PATCH /me/capacity 0 → 422
t16: PATCH /me/capacity < running → 409
t17: 注入残留 starting JSON → 重启 → /health 等到 200 → GET 任务 failed
```

## 9. 部署与运维

### 9.1 启动流程（更新）

```
┌─ uvicorn 启动
├─ lifespan startup
│   ├─ 加载 Settings (env: MAX_CONCURRENT)
│   ├─ 创建 JobStateStore
│   ├─ 创建 InstanceState(max_concurrent=MAX_CONCURRENT, ready=False)
│   ├─ recover_after_restart() ← 阻塞，~1-3s
│   └─ instance_state.mark_ready()
├─ 接受 HTTP 请求
│   ├─ /health 200（已 ready）
│   ├─ PATCH /me/capacity 可用
│   └─ POST /jobs 正常
```

### 9.2 容量调整示例

```bash
# 运维: 调整并发上限为 16
curl -X PATCH http://<instance>:8080/api/v1/workers/me/capacity \
  -H 'Content-Type: application/json' \
  -d '{"max_concurrent": 16}'

# 调整低于当前运行数 → 409
curl -X PATCH .../capacity -d '{"max_concurrent": 1}'  # 当前跑 4 个
# {"detail": "New max (1) less than current running (4)"}
```

### 9.3 故障恢复示例

```bash
# 实例崩溃后重启
# 启动期间 /health 返回 503
curl -i http://<instance>:8080/health
# HTTP/1.1 503 Service Unavailable
# {"detail": "Instance recovering after restart"}

# recover 完成后
curl http://<instance>:8080/health
# {"status": "healthy", "checks": {...}}

# 残留任务已被标记 failed
curl http://<instance>:8080/api/v1/jobs/<job_id>
# {"status": "failed",
#  "error_message": "Instance crashed; PID 12345 not in current session",
#  ...}
```

## 10. 验收标准

| 编号 | 场景 | 验收口径 |
|------|------|----------|
| AC-P3-1 | 启动无残留任务 | recover 是 no-op；/health 立即 200 |
| AC-P3-2 | 启动有 starting 残留 | 标记 failed，文案含 "Instance crashed before subprocess started" |
| AC-P3-3 | 启动有 running 残留（PID 不存在） | 标记 failed，文案含 "PID ... not in current session" |
| AC-P3-4 | 启动有 finalizing 残留 | 标记 failed，文案含 "Instance crashed during finalization" |
| AC-P3-5 | recover 期间 /health | 返回 503 |
| AC-P3-6 | recover 完成后 /health | 返回 200 |
| AC-P3-7 | PATCH capacity 合法值 | 200 + 立即生效（is_at_capacity 用新值） |
| AC-P3-8 | PATCH capacity < running | 409 + 文案含新值与当前值 |
| AC-P3-9 | PATCH capacity <= 0 | 422 |
| AC-P3-10 | PATCH capacity 字段缺失 | 422 |
| AC-P3-11 | PATCH 期间实例未 ready | 503 |
| AC-P3-12 | PATCH 后重启实例 | capacity 回到环境变量值 |
| AC-P3-13 | 黑盒集成 | opencompass/ 0 diff |

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| PID 复用（lifespan startup 期间） | 残留任务被误判为"进程仍在" | startup 串行执行窗口期极短；可接受 |
| recover 时间过长 | /health 长时间 503 | 仅扫描 NFS 一个目录，实测 < 1s；后续可加超时 |
| PATCH 与 acquire 并发 | 短暂窗口期 max 错误 | 共享 asyncio.Lock，无窗口 |
| 状态文件大批残留（崩溃时 100+ 任务） | recover 慢 | 串行处理每个 ~5ms；100 任务约 0.5s |

## 12. 未来 Phase（明确推迟）

- **Phase 4+**：finalizing 状态重跑 summarizer（需先有独立 summarizer 模块）
- **Phase 4+**：capacity 持久化到 NFS JSON
- **Phase 4+**：capacity 调整硬上限配置（环境变量）
- **Phase 5+**：调度生效时间（scheduled apply）
- **Phase 5+**：跨实例 capacity 视图（仅 Java 端聚合，本服务不参与）

## 13. 开放问题

无。