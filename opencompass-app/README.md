# opencompass-app

OpenCompass 评测任务的最小调度服务（FastAPI）。本服务**不**修改 OpenCompass 源码，
仅通过 `subprocess` + 动态生成的 config 文件调用 OC CLI。

## 范围

闭环覆盖 9 个端点（MVP 4 + Phase 2 3 + Phase 3 2）：

| 端点 | 方法 | 说明 | 阶段 |
|------|------|------|------|
| `/api/v1/jobs` | POST | 创建并启动一个评测任务 | MVP |
| `/api/v1/jobs/{job_id}` | GET | 查询任务状态 | MVP |
| `/api/v1/jobs` | GET | 列表 + 过滤 + 分页 | Phase 2 |
| `/api/v1/jobs/{job_id}/stop` | POST | 任务停止（CANCELLING+CANCELLED） | Phase 2 |
| `/api/v1/jobs/{job_id}` | DELETE | 删除任务（仅限终态） | Phase 2 |
| `/api/v1/workers/me/free` | GET | 当前实例空闲 worker 数 | MVP |
| `/api/v1/workers/me/capacity` | PATCH | 动态调整并发上限（PRD FR-3.3） | Phase 3 |
| `/health` | GET | 健康检查（recover 期间返 503） | MVP / Phase 3 |

额外能力：
- **启动恢复** `recover_after_restart()`：lifespan startup 扫描残留状态，
  残留 starting/running/cancelling/finalizing 任务标记为 failed（PRD FR-6）。

## 架构图

```
HTTP Client → FastAPI → opencompass subprocess
                ↓
        NFS JSON 状态文件（原子写、CAS 变更）
```

完整设计：[`docs/opencompass-scheduler-design.md`](../../docs/opencompass-scheduler-design.md)
MVP 设计：[`docs/superpowers/specs/2026-08-09-opencompass-app-mvp-design.md`](../../docs/superpowers/specs/2026-08-09-opencompass-app-mvp-design.md)
Phase 2 设计：[`docs/superpowers/specs/2026-08-09-opencompass-app-phase2-design.md`](../../docs/superpowers/specs/2026-08-09-opencompass-app-phase2-design.md)
Phase 3 设计：[`docs/superpowers/specs/2026-08-11-opencompass-app-phase3-design.md`](../../docs/superpowers/specs/2026-08-11-opencompass-app-phase3-design.md)

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
    ├── recovery.py              # recover_after_restart + is_pid (Phase 3)
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

## Phase 3：恢复 + 动态容量

### `recover_after_restart()`（lifespan startup）

实例启动时串行扫描 NFS 状态目录：

| 残留状态 | 动作 |
|----------|------|
| `completed` / `failed` / `cancelled` | 跳过（已是终态） |
| `starting` | 标记 failed（`Instance crashed before subprocess started`） |
| `running` / `cancelling` | `os.kill(pid, 0)` 探测 PID；不存在则标记 failed；存活则留待运维介入 |
| `finalizing` | 标记 failed（`Instance crashed during finalization`） |

每个标记 failed 的任务都会 `reserve_for_recovery(job_id) + await release(job_id)`，
保证 in-memory `_running` 计数不残留。recover 完成前 `/health` 返回 503。

### `PATCH /api/v1/workers/me/capacity`（PRD FR-3.3）

```bash
curl -X PATCH http://localhost:8080/api/v1/workers/me/capacity \
    -H 'content-type: application/json' \
    -d '{"max_concurrent": 16}'
```

- Pydantic 校验：`max_concurrent > 0`，否则 422
- 业务校验：低于当前 `running_count` 时返 409
- 立即生效（修改 in-memory `instance_state.max_concurrent`）
- 不持久化：实例重启后回到环境变量 `MAX_CONCURRENT`
- recover 期间返 503

## 测试策略

- 单元测试：utils、whitelists、registry、generator、subprocess_runner、recovery
- API 集成测试：`FastAPI.TestClient` + `monkeypatch` 桩掉 `subprocess_runner.start`
- 端到端：手动 `uvicorn` + `curl` 走通（见实施计划 `Phase 7.1`）
- 手动冒烟：`bash scripts/smoke_manual.sh`（23 项端点验证）
