# opencompass-app 镜像 — FastAPI 调度服务（黑盒集成 opencompass）
#
# 构建上下文必须是仓库根（含顶层 setup.py、opencompass/ 包、opencompass-app/ 服务）：
#     docker build -t opencompass-app:develop -f opencompass-app/Dockerfile .
#
# 关键：opencompass/ 不是独立可 pip install 包 — 仓库根的 setup.py 用
# `find_packages()` 把 opencompass/ 作为子包一起打包。所以必须
# `pip install -e .`（在仓库根），而不是 `pip install -e opencompass/`。
#
# 镜像内布局：
#     /app/opencompass/        ← OC 源码子包（被 setup.py 找到）
#     /app/opencompass-app/    ← FastAPI 服务代码
#     /data/opencompass        ← 运行时挂载（OC_DATA_ROOT）
#
# 关键约束：
# - OC 不打 wheel，源码安装保证与 develop 分支一致
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
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# === 1. 装 opencompass 运行时依赖（来自仓库根 requirements/runtime.txt）===
# 包含 torch / transformers / sentence_transformers / mmengine-lite 等
COPY requirements/runtime.txt /tmp/oc-runtime.txt
RUN pip install -r /tmp/oc-runtime.txt

# === 2. 装 opencompass（仓库根 pip install -e）===
# 关键：setup.py 在仓库根，opencompass/ 是被 find_packages() 发现的子包。
# 必须 COPY 顶层 setup.py 等关键文件并在仓库根 build，不能用 pip install -e opencompass/。
# opencompass/ 内部的 configs/、datasets/ 等子目录会被 pip install 自动包含。
# requirements/runtime.txt 是 setup.py 的 install_requires，相对路径读取，必须在 /app/ 下。
COPY setup.py MANIFEST.in README.md /app/
COPY requirements/ /app/requirements/
COPY opencompass/ /app/opencompass/
COPY dataset-index.yml /app/dataset-index.yml

# 装 opencompass 本体（setup.py 会再次解析 requirements/runtime.txt，可以接受）
RUN pip install --no-deps -e /app

# === 3. NLTK punkt（OC 部分数据集需要；setup.py 仅在 install 时下载，-e 不触发）===
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

# 健康检查：start-period=15s 给 recover 留时间
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8080/health -o /dev/null || exit 1

# 启动命令（启动脚本可覆盖）
CMD ["python", "-m", "app.main"]