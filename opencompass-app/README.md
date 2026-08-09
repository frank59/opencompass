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
