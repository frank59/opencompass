# OpenCompass-App Phase 2 设计文档

| 项目 | 内容 |
|------|------|
| 文档版本 | v1.0 |
| 编制日期 | 2026-08-09 |
| 关联文档 | [`opencompass-scheduler-design.md`](../../opencompass-scheduler-design.md) v1.4 |
| 范围 | `opencompass-app/` 子项目 Phase 2 扩展 |
| 文档状态 | 已批准，进入实施计划阶段 |
| 关联 MVP | [`2026-08-09-opencompass-app-mvp-design.md`](2026-08-09-opencompass-app-mvp-design.md) |

## 1. 目标与非目标

### 1.1 目标

在 MVP 闭环基础上扩展 3 个能力：

- **任务停止**：客户端主动取消正在运行的评测任务
- **任务列表**：分页 + 多维过滤查询
- **任务删除**：清理已完成/失败/已取消的终态任务

### 1.2 非目标（明确不做）

仍保留在 Phase 3+ 或独立 spec：

- ❌ `recover_after_restart()` 启动时故障恢复
- ❌ `PATCH /api/v1/workers/me/capacity` 调整并发上限
- ❌ Java 上游调度器
- ❌ Dockerfile / docker-compose / wheels 离线准备
- ❌ 多模型任务的 sub-status 跟踪

## 2. 关键决策（与 MVP 复用对照）

| 决策点 | 选型 | 理由 |
|--------|------|------|
| 强制终止方式 | SIGTERM + 30s grace + SIGKILL | 兼容 OC 进程的 signal handler |
| 列表分页 | offset + limit | 与设计文档 §10.1.5 一致 |
| 删除状态约束 | 只允许终态删除 | 避免误删活进程 |
| stop 权限 | 严格 instance_id 检查 | 与设计文档 §10.1.3 一致 |
| 可停止状态 | starting + running | finalizing 进程已退出 |

## 3. 状态机扩展

### 3.1 JobStatus 增加两个值

```python
class JobStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"   # 新
    CANCELLED = "cancelled"     # 新
```

### 3.2 状态迁移图

```
STARTING  --create_job-->  STARTING
STARTING  --start ok-->    RUNNING
STARTING  --start fail-->  FAILED
STARTING  --POST /stop-->  CANCELLING --after SIGKILL/exit--> CANCELLED

RUNNING   --proc exit 0--> FINALIZING --> COMPLETED
RUNNING   --proc exit N--> FINALIZING --> FAILED
RUNNING   --POST /stop-->  CANCELLING --after SIGKILL/exit--> CANCELLED

COMPLETED / FAILED / CANCELLED  --DELETE--> (deleted)
```

### 3.3 不可操作状态

- `CANCELLING`：进程已 SIGTERM，状态尚未落盘。此状态不接收第二次 /stop（409）。
- `FINALIZING`：进程刚退出，状态过渡中。MVP 中已不允许操作。
- `COMPLETED` / `FAILED` / `CANCELLED`：终态。可 DELETE（204）。

## 4. 架构与数据流

### 4.1 文件变更清单

```
opencompass-app/
├── app/
│   ├── models/
│   │   ├── enums.py                       # 改：+CANCELLING/+CANCELLED
│   │   └── response.py                    # 改：+cancelled_by
│   ├── api/
│   │   └── jobs.py                        # 改：+stop / list / delete
│   ├── stores/
│   │   └── nfs_state.py                   # 改：+list_all（带 metadata）
│   ├── executor/
│   │   └── subprocess_runner.py           # 改：+request_cancel
│   └── core/
│       └── state.py                       # （不变，由 jobs.py 协调）
└── tests/
    ├── test_enums.py                      # 改：+CANCELLING/+CANCELLED
    ├── test_subprocess_runner.py          # 改：+request_cancel
    ├── test_nfs_state.py                  # 改：+list_all
    └── test_jobs_api.py                   # 改：+stop / list / delete
```

### 4.2 subprocess_runner 扩展

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

`wait_and_finalize` 增加分支：

```python
if current["status"] == JobStatus.CANCELLING.value:
    final_status = JobStatus.CANCELLED.value
    err = "cancelled by user"
elif rc == 0:
    final_status = JobStatus.COMPLETED.value
    err = None
else:
    final_status = JobStatus.FAILED.value
    err = f"opencompass exit {rc}"
```

## 5. API 契约

### 5.1 POST /api/v1/jobs/{job_id}/stop

| 状态码 | 含义 | 响应体 |
|--------|------|--------|
| 202 Accepted | 已发停止信号 | `{"job_id": "...", "status": "cancelling"}` |
| 403 Forbidden | 任务不属于本实例 | `{"detail": "job owned by other instance: X"}` |
| 404 Not Found | 任务不存在 | `{"detail": "job not found"}` |
| 409 Conflict | 任务不在可停止状态 | `{"detail": "cannot stop job in status X"}` |

**流程**：
1. 读 state → 404 if None
2. 检查 `instance_id` → 403 if not
3. 检查 `status` in {STARTING, RUNNING} → 409 if not
4. CAS 写盘：STARTING/RUNNING → CANCELLING（原子）
   - 失败 → 409 "already cancelling"
5. 取 `instance_state.get_process(job_id)`，若存在 → `await request_cancel(proc)`
   - 进程不在本实例：状态已转 CANCELLING，但无 signal（依赖实例不可控）
6. 返回 202

### 5.2 GET /api/v1/jobs

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `status` | string | - | 单值过滤（取 JobStatus 任意值） |
| `model_path` | string | - | 子串匹配任一 model.path |
| `all` | bool | false | true=全部实例，false=仅本实例 |
| `limit` | int | 50 | 1-500 |
| `offset` | int | 0 | ≥0 |

响应：
```json
{
  "items": [JobResponse, ...],
  "total": 123,
  "limit": 50,
  "offset": 0
}
```

排序：按 `created_at` 倒序。

**过滤流程**：
1. `JobStateStore.list_all()` 读 NFS 全部 state 文件
2. Python 过滤：`status` 严格相等 / `model_path` 子串 / `instance_id` 是否本实例
3. 排序 + offset/limit 切片
4. 解析失败的 state 文件：log warning 后跳过

### 5.3 DELETE /api/v1/jobs/{job_id}

| 状态码 | 含义 |
|--------|------|
| 204 No Content | 已删除 |
| 404 Not Found | 任务不存在 |
| 409 Conflict | 任务非终态（completed/failed/cancelled） |

**流程**：
1. 读 state → 404 if None
2. 检查 `status` in {COMPLETED, FAILED, CANCELLED} → 409 if not
3. 删除 NFS state 文件（unlink）
4. 返回 204

### 5.4 GET /api/v1/jobs/{job_id}（响应扩展）

- 状态字段允许返回 `cancelling` / `cancelled`
- `error_message` 取消时为 `"cancelled by user"`

## 6. 错误处理

| 场景 | 处理 |
|------|------|
| stop 时进程已退 | 状态仍转 CANCELLING（写盘），不调用 SIGTERM |
| stop 时 NF 状态文件丢失 | 404 |
| stop CAS 写失败 | 409 "already cancelling" |
| DELETE 时正在 CANCELLING | 409 "cannot delete in status cancelling" |
| GET /jobs 状态文件解析失败 | 跳过该条（log warning） |
| request_cancel 进程已 None | 立即返回 |
| 跨实例 stop 绕过：进程不在本实例 | 状态转 CANCELLING，但无 signal；依赖后续 recover |

## 7. 测试策略

### 7.1 新增/扩展测试

- `test_enums.py` — 7 个 JobStatus 值（含 2 个新）
- `test_subprocess_runner.py` — `request_cancel` 3 个用例：
  - 进程已退 → 立即返回
  - SIGTERM 成功 → wait 即可
  - 超时 → SIGKILL 兜底
- `test_nfs_state.py` — `list_all` 2 个用例：返回所有 vs 过滤 .tmp
- `test_jobs_api.py` — 扩 8 个用例：
  - stop 202 + 状态转 CANCELLING
  - stop 403 跨实例
  - stop 404 不存在
  - stop 409 终态
  - stop 409 重复 stop
  - GET /jobs 列表（仅本实例 + all=true）
  - GET /jobs 三过滤（status / model_path / all）
  - GET /jobs 分页（offset/limit）
  - DELETE 204 终态
  - DELETE 409 非终态
  - DELETE 404

### 7.2 不测

- 真实的 SIGTERM 时序（用 AsyncMock 桩 subprocess）
- NFS 跨实例 stop 的进程清理（依赖外部）

## 8. 实施计划

预计 12 个任务，3 个阶段：

| 阶段 | 任务 | 概述 |
|------|------|------|
| 1 数据层 | 3 | JobStatus 扩展 + list_all + Pydantic 响应 |
| 2 核心引擎 | 3 | request_cancel + wait_and_finalize cancel 路径 + atomic CAS 写辅助 |
| 3 API 层 | 4 | POST /stop + GET /jobs + DELETE + 全套测试 |
| 4 联调 | 2 | 集成测试 + 文档更新 |

每个任务遵循 TDD：先写失败测试 → 跑红 → 写实现 → 跑绿 → 提交。

## 9. Definition of Done

- [ ] `pytest tests/ -v` 全部通过（≥ 90 用例）
- [ ] `ruff check app/ tests/` All checks passed
- [ ] POST /stop 跨实例返回 403（用 fake instance_id 验证）
- [ ] GET /jobs 三过滤维度（status / model_path / all）正确
- [ ] DELETE 拒非终态
- [ ] 真实 subprocess 启动后 POST /stop 触发 SIGTERM（手测）
- [ ] `opencompass/` 源码 `git diff` 为空
- [ ] README + spec 同步更新
