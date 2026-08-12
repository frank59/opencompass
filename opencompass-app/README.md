# opencompass-app

OpenCompass 评测任务的最小调度服务（FastAPI）。本服务**不**修改 OpenCompass 源码，
仅通过 `subprocess` + 动态生成的 config 文件调用 OC CLI。

## 范围

闭环覆盖 10 个端点（MVP 4 + Phase 2 3 + Phase 3 2 + Phase 4 1）：

| 端点 | 方法 | 说明 | 阶段 |
|------|------|------|------|
| `/api/v1/jobs` | POST | 创建并启动一个评测任务 | MVP |
| `/api/v1/jobs/{job_id}` | GET | 查询任务状态 | MVP |
| `/api/v1/jobs` | GET | 列表 + 过滤 + 分页 | Phase 2 |
| `/api/v1/jobs/{job_id}/stop` | POST | 任务停止（CANCELLING+CANCELLED） | Phase 2 |
| `/api/v1/jobs/{job_id}` | DELETE | 删除任务（仅限终态） | Phase 2 |
| `/api/v1/jobs/{job_id}/log` | GET | 任务执行日志分页读取 | Phase 4 |
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

## Phase 4：任务执行日志

**动机**：原 MVP 把 OC 子进程 stdout 重定向到 PIPE 但没人读取，进程退出后日志丢失，调试只能看 exit_code + 一行 error_message。

**改动**：
- `subprocess_runner.start()` 接受 `log_path` 参数，打开 unbuffered 文件把 stdout/stderr（合并）写入
- 日志路径：`{oc_data_root}/workspace/_in_progress/{job_id}/run_001/logs/opencompass.log`
- `proc._log_fp` 保留 fp 引用至 wait_and_finalize（防 GC 关 fd 触发子进程 SIGPIPE）
- 新端点 `GET /api/v1/jobs/{job_id}/log?start_line=&limit=&tail=` 按行分页读取
- `JobResponse` 增加 `log_path` 字段

**日志端点用法**：

```bash
# 第 1 页（从第 0 行读 100 行）
curl 'http://host/api/v1/jobs/job_xxx/log?start_line=0&limit=100'

# 下一页（从第 100 行读 100 行）
curl 'http://host/api/v1/jobs/job_xxx/log?start_line=100&limit=100'

# 最后 N 行（tail 模式，忽略 start_line）
curl 'http://host/api/v1/jobs/job_xxx/log?tail=true&limit=200'

# 响应
# {
#   "job_id": "...",
#   "log_path": "/data/opencompass/workspace/_in_progress/.../opencompass.log",
#   "total_lines": 1234,
#   "start_line": 100,
#   "limit": 100,
#   "returned_lines": 100,
#   "eof": false,
#   "lines": ["...", "...", ...]
# }
```

**约束**：
- `limit` 上限 1000（防 DoS）
- `start_line >= 0`（FastAPI Query 校验）
- 文件不存在 → 200 + 空 lines（任务刚创建未启动）
- job 不存在 → 404
- 访问权限与 `GET /jobs/{id}` 一致（任意实例可读）
- 单任务日志 > 100MB 时考虑改为 `seek+read` 增量读

## 测试策略

- 单元测试：utils、whitelists、registry、generator、subprocess_runner、recovery、log_helper
- API 集成测试：`FastAPI.TestClient` + `monkeypatch` 桩掉 `subprocess_runner.start`
- 端到端：手动 `uvicorn` + `curl` 走通（见实施计划 `Phase 7.1`）
- 手动冒烟：`bash scripts/smoke_manual.sh`（18 项端点验证）
- 容器黑盒：`bash opencompass-app/scripts/docker-test.sh`（10 项端点验证）
