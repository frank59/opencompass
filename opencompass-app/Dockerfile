# opencompass-app 镜像 — FastAPI 调度服务（黑盒集成 opencompass）
#
# 构建上下文必须是仓库根（含 opencompass/ 和 opencompass-app/ 两层目录）：
#     docker build -t opencompass-app:develop -f opencompass-app/Dockerfile .
#
# 镜像内布局：
#     /app/opencompass/        ← 源码 pip install -e
#     /app/opencompass-app/    ← 服务代码
#     /data/opencompass        ← 运行时挂载（OC_DATA_ROOT，含 datasets/、workspace/）
#
# 关键约束：
# - opencompass 不打 wheel，源码安装保证与 develop 分支一致
# - mmengine-lite 是 ModelWhitelist 动态扫描必需，不能省
# - 子进程 opencompass CLI 会在容器内被调用，所以 OC 必须可执行

# syntax=docker/dockerfile:1.7
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # OC-app 运行时默认配置（启动脚本可覆盖）
    PORT=8080 \
    OC_DATA_ROOT=/data/opencompass \
    MAX_CONCURRENT=4 \
    LOG_LEVEL=INFO

# 系统依赖：编译（numpy/h5py/pandas）+ git（pip install -e 需要）+ curl（健康检查）
# --no-install-recommends 避免 apt 自动装无用包
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# === 1. 装 opencompass 运行时依赖 ===
# 来自仓库根 requirements/runtime.txt（含 torch / transformers / mmengine-lite 等）
COPY requirements/runtime.txt /tmp/oc-runtime.txt
RUN pip install -r /tmp/oc-runtime.txt

# === 2. 装 opencompass 源码（pip install -e）===
# 与 develop 分支一致；OC 注册表（model / dataset / inferencer / evaluator）需要被 import
COPY opencompass/ /app/opencompass/
RUN pip install -e /app/opencompass

# === 3. NLTK punkt（OC 部分数据集需要；setup.py 只在 install 时下载，-e 不触发）===
RUN python -c "import nltk; nltk.download('punkt', download_dir='/usr/share/nltk_data')"

# === 4. 装 opencompass-app 依赖 ===
COPY opencompass-app/requirements.txt /tmp/app-reqs.txt
RUN pip install -r /tmp/app-reqs.txt

# === 5. 复制 opencompass-app 源码（不含 __pycache__/.pytest_cache，由 .dockerignore 控制）===
COPY opencompass-app/ /app/opencompass-app/

WORKDIR /app/opencompass-app

# 默认 INSTANCE_ID 为空字符串，由 app/core/instance.py 派生（hostname:port）
ENV INSTANCE_ID=

EXPOSE 8080

# 健康检查：start-period=15s 给 recover 留时间；recover 期间 /health 会返 503，
# 但 uvicorn 进程本身还活着，curl 拿到 503 也算"OK"（用 -f 会失败，改用 || true）
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8080/health -o /dev/null || exit 1

# 启动命令（启动脚本可覆盖）
CMD ["python", "-m", "app.main"]