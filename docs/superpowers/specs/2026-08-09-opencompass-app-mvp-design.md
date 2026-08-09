# OpenCompass-App MVP 设计文档

| 项目 | 内容 |
|------|------|
| 文档版本 | v1.0 |
| 编制日期 | 2026-08-09 |
| 关联设计 | [`opencompass-scheduler-design.md`](../../opencompass-scheduler-design.md) v1.4 |
| 范围 | `opencompass-app/` 子项目 MVP 闭环 |
| 文档状态 | 已批准，进入实施计划阶段 |

## 1. 目标与非目标

### 1.1 目标

实现 [`opencompass-app/`](../../opencompass-app/) 子项目 MVP（Minimum Viable Product）—— 即打通"提交评测任务 → 生成 OpenCompass config → 启动 subprocess → 状态持久化 → 查询进度"的最小闭环。覆盖设计文档 [`opencompass-scheduler-design.md`](../../opencompass-scheduler-design.md) §12.1.1 中标记为 P0 的 FastAPI 部分的最薄切片。

### 1.2 非目标（明确不做）

Phase 2 再补，本 spec **不**包含：

- ❌ `POST /api/v1/jobs/{id}/stop` 停止任务
- ❌ `DELETE /api/v1/jobs/{id}` 删除任务
- ❌ `GET /api/v1/jobs` 列出任务（带过滤参数）
- ❌ `recover_after_restart()` 启动时故障恢复
- ❌ `PATCH /api/v1/workers/me/capacity` 调整并发上限
- ❌ Java 上游调度器（独立 Java 子项目）
- ❌ Dockerfile / docker-compose / wheels 离线准备（独立部署 spec）
- ❌ 多模型任务的 sub-status 跟踪（Job 整体 running 即可）

## 2. 架构概览

### 2.1 整体定位

`opencompass-app/` 是 FastAPI 调度服务的源码子项目，位于本仓库根的 `./opencompass-app/` 目录，与 `opencompass/`（评测引擎）平级。本 spec 实现其中 MVP 部分。

```
┌──────────────────────┐
│  HTTP Client (Java)  │
└──────────┬───────────┘
           │ HTTPS
┌──────────▼────────────┐
│  FastAPI app (MVP)    │ ←── 本 spec 范围
│  ┌────────────────┐   │
│  │ api/jobs.py    │   │  POST /jobs
│  │ api/workers.py │   │  /workers/me/free, /health
│  │ core/state.py  │   │  InstanceState (worker pool)
│  │ stores/nfs...  │   │  JobStateStore
│  │ oc_config/...  │   │  generate_config
│  │ executor/...   │   │  subprocess_runner
│  └────────────────┘   │
└──────────┬────────────┘
           │ subprocess: opencompass <config> -w ... -r ...
┌──────────▼────────────┐
│  OpenCompass Engine   │  ← 不修改，黑盒集成
└───────────────────────┘
```

### 2.2 核心集成约束（来自设计文档 §1.1）

- ❌ **不修改** `opencompass/` 目录下任何源码
- ✅ 仅通过 `from opencompass.X import Y` 调用 OC 公开 API（白名单扫描、registry 读取）
- ✅ 通过 `subprocess` + `-r` 自定义目录名调用 OC CLI
- ✅ 通过 mmengine `read_base()` + 内联 dict 生成 config 文件
- ✅ 所有"白名单"动态扫描 OC 注册表，硬编码类名字符串视为违规

## 3. 目录结构

```
opencompass-app/
├── app/
│   ├── __init__.py
│   ├── main.py                            # FastAPI app 工厂 + lifespan
│   ├── api/
│   │   ├── __init__.py
│   │   ├── jobs.py                        # POST /api/v1/jobs, GET /api/v1/jobs/{id}
│   │   └── workers.py                     # GET /api/v1/workers/me/free, GET /health
│   ├── core/
│   │   ├── __init__.py
│   │   ├── settings.py                    # Pydantic Settings，环境变量读取
│   │   ├── instance.py                    # INSTANCE_ID 派生
│   │   ├── state.py                       # InstanceState（worker 池）
│   │   ├── dataset_registry.py            # DatasetRegistry（dataset-index.yml 查表）
│   │   ├── model_whitelist.py             # ModelWhitelist（BaseAPIModel 子类扫描）
│   │   └── dataset_whitelist.py           # DatasetWhitelist（4 类白名单）
│   ├── oc_config/
│   │   ├── __init__.py
│   │   └── generator.py                   # generate_config（字符串拼装 + atomic write）
│   ├── executor/
│   │   ├── __init__.py
│   │   └── subprocess_runner.py           # start / wait_and_finalize
│   ├── stores/
│   │   ├── __init__.py
│   │   └── nfs_state.py                   # JobStateStore（atomic JSON 读写）
│   ├── models/
│   │   ├── __init__.py
│   │   ├── request.py                     # CreateJobRequest, DatasetItem, ModelItem
│   │   ├── response.py                    # JobResponse, FreeWorkerCount, HealthResponse
│   │   └── enums.py                       # JobStatus, WorkerStatus
│   ├── data/
│   │   └── dataset_index.yaml             # 复制自 ../../dataset-index.yml
│   └── utils/
│       ├── __init__.py
│       ├── time.py                        # now_iso()
│       └── ids.py                         # is_valid_job_id()
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_dataset_registry.py
│   ├── test_model_whitelist.py
│   ├── test_dataset_whitelist.py
│   ├── test_nfs_state.py
│   ├── test_instance_state.py
│   ├── test_generator.py
│   ├── test_jobs_api.py
│   └── test_workers_api.py
├── pyproject.toml                         # 含 dev 依赖（pytest, httpx, pytest-asyncio）
├── requirements.txt                       # runtime 依赖
├── README.md                              # 本地开发与启动说明
└── .gitignore                             # __pycache__, .pytest_cache, *.tmp
```

## 4. 依赖

### 4.1 runtime 依赖（`requirements.txt`）

| 包 | 版本约束 | 用途 |
|----|---------|------|
| `fastapi` | `>=0.110,<0.120` | Web 框架 |
| `uvicorn[standard]` | `>=0.27,<0.30` | ASGI 服务器 |
| `pydantic` | `>=2.5,<3` | 数据模型 |
| `pydantic-settings` | `>=2.1,<3` | 环境变量 |
| `pyyaml` | `>=6.0,<7` | dataset-index.yml 解析 |
| `httpx` | `>=0.25,<0.30` | black-box 测试调用 |

### 4.2 dev 依赖（`pyproject.toml`）

| 包 | 用途 |
|----|------|
| `pytest` | 测试框架 |
| `pytest-asyncio` | async 测试 |
| `pytest-cov` | 覆盖率（可选） |
| `ruff` | 代码风格 |

### 4.3 可选依赖（设计文档白名单扫描所需）

| 包 | 用途 | 缺失时行为 |
|----|------|-----------|
| `opencompass` | 动态扫描 `BaseAPIModel` 子类、registry | 白名单 fallback 为空 + warning 日志；本机测试可正常跑 |
| `mmengine` | config 生成器内 `Config.fromfile` 校验（可选） | 跳过校验，仅字符串拼装 |

> mmengine 与 opencompass 在容器镜像内必须安装；本地开发可不装。

### 4.4 环境变量

| 变量 | 默认 | 用途 |
|------|------|------|
| `INSTANCE_ID` | `hostname:port` 自动派生 | 实例唯一标识 |
| `OC_DATA_ROOT` | `/data/opencompass` | 工作区根目录（开发时可指向 `/tmp/opencompass-dev`） |
| `MAX_CONCURRENT` | `8` | 每实例并发上限 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## 5. 数据模型

### 5.1 JobStatus 枚举（MVP 子集）

```python
class JobStatus(str, Enum):
    STARTING = "starting"          # 写 NFS 瞬时态
    RUNNING = "running"            # subprocess 已启动
    FINALIZING = "finalizing"      # 进程退出，等写终态（MVP 中间瞬态）
    COMPLETED = "completed"        # exit_code = 0
    FAILED = "failed"              # exit_code ≠ 0 或启动异常
```

> 移除 `CANCELLING` / `CANCELLED`（Phase 2 补 stop 时再加）。

### 5.2 Request / Response 模型

```python
# app/models/request.py
class ModelItem(BaseModel):
    type: str                        # 白名单内的 OC 类路径
    path: str                        # 模型名
    model_config = ConfigDict(extra="allow")  # 透传 key/openai_api_base/temperature/...

class DatasetItem(BaseModel):
    abbr: str                        # 必填；内联 dict 时还是用 abbr 命名
    type: str | None = None
    path: str | None = None
    reader_cfg: dict | None = None
    infer_cfg: dict | None = None
    eval_cfg: dict | None = None

class CreateJobRequest(BaseModel):
    job_id: str
    datasets: list[DatasetItem]                  # ≥1
    models: list[ModelItem]                       # ≥1
    priority: int = 5                             # 1~10，MVP 不使用
    max_runtime_seconds: int = 7200               # MVP 不强制使用（subprocess 自行超时）
    created_by: str | None = None

# app/models/response.py
class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    instance_id: str
    datasets: list[DatasetItem]
    models: list[ModelItem]
    config_path: str
    work_dir: str
    created_at: str                               # ISO8601
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    error_message: str | None
    pid: int | None
    created_by: str | None

class FreeWorkerCount(BaseModel):
    available: int
    max: int
    running: int

class HealthCheck(BaseModel):
    status: str                                   # "healthy" / "degraded"
    checks: dict[str, str]                        # {nfs_state: "ok", opencompass_binary: "ok"}
```

### 5.3 NFS Job JSON Schema

存储路径：`${OC_DATA_ROOT}/workspace/state/jobs/<job_id>.json`

```json
{
  "job_id": "job_20260808_abc123",
  "status": "running",
  "instance_id": "pytest-instance",
  "datasets": [{"abbr": "gsm8k"}, {"abbr": "mmlu"}],
  "models": [{
    "type": "opencompass.models.openai_api.OpenAISDK",
    "path": "Qwen3-1.7B-Ynja",
    "key": "sk-xxxx",
    "openai_api_base": "http://..."
  }],
  "priority": 5,
  "max_runtime_seconds": 7200,
  "config_path": ".../job_xxx/run_001/configs/job_xxx.py",
  "work_dir": ".../job_xxx/run_001",
  "created_at": "2026-08-09T10:30:00Z",
  "started_at": "2026-08-09T10:30:00.523Z",
  "finished_at": null,
  "exit_code": null,
  "error_message": null,
  "pid": 12345,
  "created_by": "tenant_alice"
}
```

## 6. 模块设计

### 6.1 `app/utils/ids.py`

```python
import re
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
def is_valid_job_id(job_id: str) -> bool:
    return bool(_JOB_ID_RE.match(job_id))
```

### 6.2 `app/utils/time.py`

```python
from datetime import datetime, timezone
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
```

### 6.3 `app/core/settings.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    instance_id: str | None = None
    oc_data_root: str = "/data/opencompass"
    max_concurrent: int = 8
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)
settings = Settings()
```

环境变量映射：`INSTANCE_ID` / `OC_DATA_ROOT` / `MAX_CONCURRENT` / `LOG_LEVEL`。

### 6.4 `app/core/instance.py`

```python
import socket, os
_INSTANCE_ID: str | None = None
def get_instance_id() -> str:
    """返回 INSTANCE_ID 环境变量，否则 <hostname>-<pid>"""
    global _INSTANCE_ID
    if _INSTANCE_ID is None:
        _INSTANCE_ID = os.getenv("INSTANCE_ID") or f"{socket.gethostname()}-{os.getpid()}"
    return _INSTANCE_ID
```

### 6.5 `app/stores/nfs_state.py`

```python
class JobStateStore:
    """NFS JSON 状态持久化。任意实例可读，写者独占。"""
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _path(self, job_id: str) -> Path:
        return self.base_dir / f"{job_id}.json"
    
    def write_atomic(self, job_id: str, payload: dict) -> None:
        """temp file + fsync + os.replace，NFS 上保证原子性"""
        target = self._path(job_id)
        fd, tmp = tempfile.mkstemp(dir=self.base_dir, prefix=f".{job_id}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, target)
        except Exception:
            if os.path.exists(tmp): os.unlink(tmp)
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
        if not self.base_dir.is_dir(): return []
        return sorted(p.stem for p in self.base_dir.glob("*.json") if not p.name.startswith("."))
```

### 6.6 `app/core/state.py`

```python
class InstanceState:
    def __init__(self, max_concurrent: int):
        self.max_concurrent = max_concurrent
        self._running: set[str] = set()
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._lock = asyncio.Lock()
    
    # O(1) 读（热路径，无锁）
    def running_count(self) -> int: return len(self._running)
    def available_slots(self) -> int: return max(0, self.max_concurrent - len(self._running))
    def is_at_capacity(self) -> bool: return len(self._running) >= self.max_concurrent
    
    # 写路径
    async def try_acquire(self, job_id: str) -> bool:
        async with self._lock:
            if self.is_at_capacity(): return False
            self._running.add(job_id); return True
    
    async def track_process(self, job_id: str, proc: asyncio.subprocess.Process):
        async with self._lock:
            self._processes[job_id] = proc
    
    async def release(self, job_id: str):
        async with self._lock:
            self._running.discard(job_id)
            self._processes.pop(job_id, None)

# 全局单例（在 main.py lifespan 中实例化）
instance_state: InstanceState | None = None
def get_instance_state() -> InstanceState:
    if instance_state is None:
        raise RuntimeError("InstanceState not initialized")
    return instance_state
```

### 6.7 `app/core/dataset_registry.py`

```python
class DatasetRegistry:
    """内置数据集查表。
    主数据源：app/data/dataset_index.yaml（229 项官方维护）。
    Fallback：扫描 opencompass/configs/datasets/<name>/<name>_gen.py。"""
    _INDEX: dict[str, tuple[str, str]] | None = None
    
    @classmethod
    def _load(cls) -> dict[str, tuple[str, str]]:
        if cls._INDEX is not None: return cls._INDEX
        path = Path(__file__).parent / "data" / "dataset_index.yaml"
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        idx = {}
        for entry in raw:
            (abbr, info), = entry.items()
            cfg_path = info["configpath"]   # e.g. opencompass/configs/datasets/mmlu/mmlu_gen.py
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
        if abbr not in cls._load():
            raise KeyError(f"dataset '{abbr}' not in registry")
        return cls._load()[abbr]
```

### 6.8 `app/core/model_whitelist.py`

```python
class ModelWhitelist:
    _TYPES: frozenset[str] | None = None
    
    @classmethod
    def types(cls) -> frozenset[str]:
        if cls._TYPES is not None: return cls._TYPES
        try:
            import opencompass.models as pkg
            from opencompass.models.base_api import BaseAPIModel
            found = set()
            for name in dir(pkg):
                obj = getattr(pkg, name)
                if isinstance(obj, type) and issubclass(obj, BaseAPIModel) and obj is not BaseAPIModel:
                    found.add(f"opencompass.models.{obj.__name__}")
            cls._TYPES = frozenset(found)
        except ImportError:
            log.warning("opencompass not installed; model whitelist empty")
            cls._TYPES = frozenset()
        return cls._TYPES
    
    @classmethod
    def validate(cls, model_dict: dict) -> None:
        if not model_dict.get("type"): raise ValueError("missing 'type' field")
        if not model_dict.get("path"): raise ValueError("missing 'path' field")
        if model_dict["type"] not in cls.types():
            raise ValueError(f"model type '{model_dict['type']}' not in whitelist")
```

### 6.9 `app/core/dataset_whitelist.py`

```python
class DatasetWhitelist:
    """覆盖 5 个字段位置的白名单：dataset.type + infer_cfg.{prompt_template,retriever,inferencer}.type + eval_cfg.evaluator.type"""
    _DATASET: frozenset[str] | None = None
    _EVAL: frozenset[str] | None = None
    _INFER: frozenset[str] | None = None
    _RETRIEVER: frozenset[str] | None = None
    
    @classmethod
    def dataset_types(cls) -> frozenset[str]:
        if cls._DATASET is None:
            try:
                from opencompass.registry import LOAD_DATASET
                cls._DATASET = frozenset(LOAD_DATASET._module_dict.keys())
            except ImportError:
                cls._DATASET = frozenset()
        return cls._DATASET
    
    # evaluator_types, inferencer_types, retriever_types 类似实现
    
    @classmethod
    def validate_dataset_item(cls, ds: dict) -> None:
        if not isinstance(ds, dict): raise ValueError("dataset item must be a dict")
        if not ds.get("abbr"): raise ValueError("missing 'abbr' field")
        
        # 自定义数据集
        type_str = ds.get("type")
        if type_str not in cls.dataset_types():
            raise ValueError(f"dataset type '{type_str}' not in whitelist")
        path = ds.get("path", "")
        if not path.startswith("/data/opencompass/datasets/customer/"):
            raise ValueError(f"path must start with /data/opencompass/datasets/customer/, got: {path}")
        # 子项白名单（4 个字段位置）
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

### 6.10 `app/oc_config/generator.py`

```python
def _in_progress_dir(job_id: str, run_dir: str) -> Path:
    """生成 .../workspace/_in_progress/<job_id>/<run_dir>/configs 路径。"""
    return Path(settings.oc_data_root) / "workspace" / "_in_progress" / job_id / run_dir / "configs"


async def generate_config(req: CreateJobRequest, run_dir: str = "run_001") -> str:
    config_dir = _in_progress_dir(req.job_id, run_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{req.job_id}.py"
    
    # [1] 数据集
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
    
    # [2] 模型
    model_assigns: list[str] = []
    model_aliases: list[str] = []
    for idx, m in enumerate(req.models):
        alias = _model_alias(m.path, idx)
        model_assigns.append(f"{alias} = {_dump(m.model_dump())}")
        model_aliases.append(alias)
    
    # [3] 源串
    source = _render(dataset_imports, dataset_assigns, dataset_aliases,
                     model_assigns, model_aliases)
    
    # [4] 原子写
    tmp = config_path.with_suffix(".py.tmp")
    tmp.write_text(source, encoding="utf-8")
    os.replace(tmp, config_path)
    return str(config_path)


def _model_alias(path: str, idx: int) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in path)
    return f"model_{safe.lower()}_{idx}"

def _dataset_alias(abbr: str, idx: int) -> str:
    safe = "".join(ch if (ch.isalnum() or "\u4e00" <= ch <= "\u9fff") else "_" for ch in abbr)
    return f"dataset_{safe}_{idx}"

def _dump(obj) -> str:
    return pprint.pformat(obj, indent=4, width=88, sort_dicts=False)

def _render(dataset_imports, dataset_assigns, dataset_aliases,
            model_assigns, model_aliases) -> str:
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
```

### 6.11 `app/executor/subprocess_runner.py`

```python
async def start(job_id: str, config_path: str) -> asyncio.subprocess.Process:
    """启动 opencompass subprocess。

    参数布局（与设计文档 §8.1 一致）：
        config_path = .../<job_id>/<run_dir>/configs/<job_id>.py
        -w 指向    = .../<job_id>/            （run_dir 的父目录）
        -r 指向    = <run_dir>                （run_dir 名）
    """
    config_p = Path(config_path)
    run_dir = config_p.parent.parent        # .../<job_id>/<run_dir>/
    cmd = [
        "opencompass",
        config_path,
        "-w", str(run_dir.parent),          # .../<job_id>/
        "-r", run_dir.name,                 # <run_dir>
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    return proc

async def wait_and_finalize(job_id: str, proc: asyncio.subprocess.Process,
                            state_store: JobStateStore,
                            instance_state: InstanceState) -> None:
    rc = await proc.wait()
    current = state_store.read(job_id)
    if current is None: return
    
    final_status = "completed" if rc == 0 else "failed"
    state_store.write_atomic(job_id, {**current,
        "status": final_status,
        "finished_at": now_iso(),
        "exit_code": rc,
        "error_message": None if rc == 0 else f"opencompass exit {rc}",
    })
    await instance_state.release(job_id)
```

### 6.12 `app/api/jobs.py`

```python
router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

@router.post("", status_code=201, response_model=JobResponse)
async def create_job(req: CreateJobRequest):
    # 校验流程见设计 §C.4
    ...

@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    state = get_state_store().read(job_id)
    if state is None: raise HTTPException(404, "job not found")
    return JobResponse(**state)
```

### 6.13 `app/api/workers.py`

```python
router = APIRouter(prefix="/api/v1/workers", tags=["workers"])

@router.get("/me/free", response_model=FreeWorkerCount)
async def free_workers():
    s = get_instance_state()
    return FreeWorkerCount(available=s.available_slots(), max=s.max_concurrent, running=s.running_count())

health_router = APIRouter()

@health_router.get("/health", response_model=HealthCheck)
async def health():
    checks = {}
    try:
        get_state_store().list_ids(); checks["nfs_state"] = "ok"
    except Exception as e: checks["nfs_state"] = f"fail: {e}"
    checks["opencompass_binary"] = "ok" if shutil.which("opencompass") else "missing"
    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return HealthCheck(status=overall, checks=checks)
```

### 6.14 `app/main.py`

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global instance_state, state_store
    settings_inst = Settings()
    state_store = JobStateStore(base_dir=str(Path(settings_inst.oc_data_root) / "workspace" / "state" / "jobs"))
    instance_state = InstanceState(max_concurrent=settings_inst.max_concurrent)
    yield

def create_app() -> FastAPI:
    app = FastAPI(title="opencompass-app", lifespan=lifespan)
    app.include_router(jobs_router)
    app.include_router(workers_router)
    app.include_router(health_router)
    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=False)
```

## 7. API 契约（MVP）

| 端点 | 方法 | 状态码 |
|------|------|--------|
| `POST /api/v1/jobs` | 创建并启动 | 201 / 409 / 422 / 503 |
| `GET /api/v1/jobs/{job_id}` | 查询 | 200 / 404 |
| `GET /api/v1/workers/me/free` | 空闲 worker 数 | 200 |
| `GET /health` | 健康检查 | 200 |

详细请求/响应示例与设计文档 §10.1 / §10.2 / §10.3 一致，本 spec 不再重复。

## 8. 关键流程：POST /jobs

```
[1] 校验 job_id 格式
[2] 检查 NFS 上 job_id.json 不存在（409）
[3] 校验 datasets（builtin 查 registry / 自定义走白名单 + 路径存在性）
[4] 校验 models（白名单 + 必填字段）
[5] 检查 instance_state.is_at_capacity()（503）
[6] try_acquire slot（失败 → 503）
[7] generate_config → 返回 config_path
[8] 原子写 starting 状态
[9] subprocess start
[10] track_process + 写 running 状态（含 pid）
[11] asyncio.create_task(wait_and_finalize) — 不阻塞响应
[12] 返回 201 + JobResponse(status="running")
[失败路径] 任何一步异常 → release slot + 清理 NFS 文件 + 5xx
```

## 9. 测试设计

### 9.1 单元测试（pytest）

| 测试文件 | 关键用例 |
|---------|---------|
| `test_dataset_registry.py` | `test_resolve_builtin_gsm8k_ok`；`test_is_builtin_unknown_returns_false`；`test_resolve_builtin_unknown_raises` |
| `test_model_whitelist.py` | `test_validate_missing_type`；`test_validate_missing_path`；`test_validate_unknown_type`；`test_types_empty_when_oc_not_installed` |
| `test_dataset_whitelist.py` | `test_validate_subtype_inferencer`；`test_validate_subtype_evaluator`；`test_validate_path_prefix`；`test_validate_missing_abbr` |
| `test_nfs_state.py` | `test_write_atomic_creates_file`；`test_read_missing_returns_none`；`test_write_atomic_overwrites`；`test_list_ids_filters_tmp` |
| `test_instance_state.py` | `test_is_at_capacity_false_when_empty`；`test_try_acquire_returns_false_when_full`；`test_release_idempotent`；`test_concurrent_acquire_respects_limit` |
| `test_generator.py` | `test_builtin_dataset_renders_from_import`；`test_custom_dataset_renders_inline`；`test_multi_model_renders_array`；`test_atomic_write_uses_replace` |

### 9.2 API 集成测试（FastAPI TestClient + monkeypatch）

`test_jobs_api.py`：

- `test_post_jobs_201_with_builtin_datasets`
- `test_post_jobs_201_with_custom_dataset`
- `test_post_jobs_409_when_duplicate`
- `test_post_jobs_422_unknown_builtin`
- `test_post_jobs_422_invalid_custom_type`
- `test_post_jobs_422_path_not_found`
- `test_post_jobs_503_when_at_capacity`
- `test_get_job_200`
- `test_get_job_404`

`test_workers_api.py`：

- `test_workers_me_free_returns_counts`
- `test_health_ok_when_state_writable`

### 9.3 Mock 策略（`tests/conftest.py`）

```python
@pytest.fixture
def tmp_state_store(tmp_path) -> JobStateStore:
    return JobStateStore(base_dir=str(tmp_path / "state" / "jobs"))

@pytest.fixture
def patched_state_store(monkeypatch, tmp_state_store):
    monkeypatch.setattr("app.main.state_store", tmp_state_store, raising=False)
    monkeypatch.setattr("app.api.jobs.get_state_store", lambda: tmp_state_store)
    return tmp_state_store

@pytest.fixture
def patched_subprocess(monkeypatch):
    async def fake_start(job_id, config_path):
        proc = AsyncMock()
        proc.pid = 99999
        proc.wait = AsyncMock(return_value=0)
        return proc
    monkeypatch.setattr("app.executor.subprocess_runner.start", fake_start)
    return fake_start

@pytest.fixture
def settings_override(monkeypatch):
    monkeypatch.setenv("INSTANCE_ID", "pytest-instance")
    monkeypatch.setenv("MAX_CONCURRENT", "2")
    monkeypatch.setenv("OC_DATA_ROOT", "/tmp/pytest-oc")
```

## 10. 实施顺序（tracer bullet）

```
阶段 1：脚手架
  - 创建目录结构
  - pyproject.toml + requirements.txt + .gitignore

阶段 2：原子基础设施（纯逻辑，无 import OC）
  - utils/ids.py, utils/time.py
  - models/enums.py, models/request.py, models/response.py
  - stores/nfs_state.py
  - core/state.py
  - core/settings.py, core/instance.py
  验证：pytest tests/test_nfs_state.py tests/test_instance_state.py

阶段 3：白名单与注册表
  - 复制 dataset-index.yml 到 app/data/dataset_index.yaml
  - core/dataset_registry.py
  - core/model_whitelist.py
  - core/dataset_whitelist.py
  验证：pytest tests/test_dataset_registry.py tests/test_model_whitelist.py tests/test_dataset_whitelist.py

阶段 4：config 生成器
  - oc_config/generator.py
  验证：pytest tests/test_generator.py

阶段 5：subprocess 执行器（mock 真实拉起）
  - executor/subprocess_runner.py
  验证：手动验证代码（不强求测试，因 mock 后只是 AsyncMock）

阶段 6：API 端点
  - api/jobs.py, api/workers.py
  - main.py（含 lifespan + uvicorn 入口）
  验证：pytest tests/test_jobs_api.py tests/test_workers_api.py

阶段 7：联调与文档
  - 手工启动 uvicorn，curl 走通 MVP 全链路
  - 编写 README.md
  - pytest tests/ -v 一次跑通
```

## 11. 完成定义（Definition of Done）

- [ ] `pytest tests/ -v` 全部通过（≥30 用例）
- [ ] `python -m app.main` 启动后 `curl http://localhost:8080/health` 返回 200
- [ ] `curl POST /api/v1/jobs` 含 builtin + custom dataset，能生成 config 文件并返回 201
- [ ] `curl GET /api/v1/jobs/{job_id}` 能读到 starting/running 状态
- [ ] `curl GET /api/v1/workers/me/free` 返回 `{available, max, running}`
- [ ] README.md 含本地开发指引（环境变量 / 启动命令 / 测试命令）
- [ ] 代码 `ruff check` 通过
- [ ] `opencompass/` 目录 `git diff` 仍为 0（黑盒集成原则）

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| `dataset-index.yml` 与 OC 版本不同步 | 用 pip 可升级的方式：升级 OC 时重新复制该文件 |
| mmengine 未安装导致 config 生成失败 | config 生成器只做字符串拼装，mmengine 不参与；本地开发无 mmengine 也能跑 |
| subprocess 启动失败但 state 已写 starting | `wait_and_finalize` 中兜底：读到 starting 但 proc 已死 → 标 failed |
| NFS 不可用（开发机） | `OC_DATA_ROOT` 指向 `/tmp/...` 即可绕开 |
| 中文字符在 abbr 中导致 Python 变量名非法 | `_dataset_alias` 已显式支持中文字符范围 |
| 测试时真实 subprocess 启动会污染环境 | monkeypatch `subprocess_runner.start` 为 AsyncMock |

## 附录 A · 与设计文档的章节映射

| 本 spec 章节 | 对应 design doc 章节 |
|-------------|---------------------|
| §3 目录结构 | design §5.1 |
| §5 数据模型 | design §7.1 / §7.3 |
| §6.3 settings | design §9.2（环境变量） |
| §6.5 JobStateStore | design §5.4 |
| §6.6 InstanceState | design §5.3 |
| §6.7 DatasetRegistry | design §8.6.5（数据集注册表） |
| §6.8/6.9 Whitelist | design §8.6.5 + §1.1 |
| §6.10 generator | design §8.6.3 |
| §6.11 subprocess_runner | design §5.2.3 + §8.1 |
| §6.12 jobs.py | design §5.2 |
| §6.13 workers.py | design §5.3.2 + §10.3 |
| §7 API 契约 | design §10.1 / §10.2 / §10.3 |
| §8 POST /jobs 流程 | design §6.2 |
| §10 实施顺序 | design §12.1.1（FastAPI 子集） |