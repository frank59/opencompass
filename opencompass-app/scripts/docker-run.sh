#!/usr/bin/env bash
# docker-run.sh — 启动 opencompass-app 容器
#
# 用法：
#     bash opencompass-app/scripts/docker-run.sh
#
# 环境变量覆盖：
#     PORT=8081 bash docker-run.sh
#     MAX_CONCURRENT=8 bash docker-run.sh
#     INSTANCE_ID=node-007 bash docker-run.sh
#
# 数据卷：/data/opencompass（宿主机）→ /data/opencompass（容器内）
# 端口：8080（容器内）→ 8080（宿主机，可改）
# 镜像：opencompass-app:develop
#
# 容器名：opencompass-app（重复执行会先 stop + rm 旧容器）

set -euo pipefail

RED=$'\033[0;31m'
GRN=$'\033[0;32m'
YLW=$'\033[1;33m'
NC=$'\033[0m'

log() { echo "${YLW}[docker-run]${NC} $*"; }
ok() { echo "${GRN}[docker-run]${NC} $*"; }
die() { echo "${RED}[docker-run] ERROR: $*${NC}" >&2; exit 1; }

# === 配置 ===
PORT="${PORT:-8080}"
MAX_CONCURRENT="${MAX_CONCURRENT:-4}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
INSTANCE_ID="${INSTANCE_ID:-}"
IMAGE_NAME="opencompass-app:develop"
CONTAINER_NAME="opencompass-app"
HOST_OC_DATA_ROOT="${HOST_OC_DATA_ROOT:-/data/opencompass}"

# === 预检 ===
command -v docker >/dev/null || die "docker 未安装"
docker info >/dev/null 2>&1 || die "docker daemon 不可达"

docker image inspect "$IMAGE_NAME" >/dev/null 2>&1 || die "镜像 $IMAGE_NAME 不存在，先跑 docker-build.sh"

[[ -d "$HOST_OC_DATA_ROOT" ]] || die "宿主机 OC 数据根不存在: $HOST_OC_DATA_ROOT
   预期目录结构：
       $HOST_OC_DATA_ROOT/datasets/data/   ← 静态数据
       $HOST_OC_DATA_ROOT/workspace/       ← 运行时状态（容器会创建）"

[[ -d "$HOST_OC_DATA_ROOT/datasets/data" ]] || log "警告: $HOST_OC_DATA_ROOT/datasets/data 不存在 — 容器可启动但评测任务会失败"

# === 清理旧容器 ===
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    log "发现旧容器 $CONTAINER_NAME，先停止 + 删除"
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

# === 启动 ===
log "启动容器: $CONTAINER_NAME"
log "  端口:   宿主机:$PORT → 容器:8080"
log "  数据:   $HOST_OC_DATA_ROOT → /data/opencompass"
log "  实例:   INSTANCE_ID=${INSTANCE_ID:-<空，自动派生>}"
log "  并发:   MAX_CONCURRENT=$MAX_CONCURRENT"

docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "${PORT}:8080" \
    -v "${HOST_OC_DATA_ROOT}:/data/opencompass" \
    -e OC_DATA_ROOT=/data/opencompass \
    -e MAX_CONCURRENT="$MAX_CONCURRENT" \
    -e LOG_LEVEL="$LOG_LEVEL" \
    -e PORT=8080 \
    -e INSTANCE_ID="$INSTANCE_ID" \
    -e PYTHONUNBUFFERED=1 \
    --log-driver json-file \
    --log-opt max-size=10m \
    --log-opt max-file=3 \
    "$IMAGE_NAME"

# === 等待 /health 就绪（最长 30s）===
log "等待服务就绪（http://localhost:$PORT/health）..."
local_ok=""
for i in $(seq 1 60); do
    sleep 0.5
    code=$(curl -s -o /tmp/health.json -w '%{http_code}' "http://localhost:$PORT/health" 2>/dev/null || echo "000")
    if [[ "$code" == "200" ]]; then
        local_ok="yes"
        ok "服务就绪（${i} × 0.5s）"
        cat /tmp/health.json | python3 -m json.tool 2>/dev/null || cat /tmp/health.json
        echo ""
        break
    fi
done

if [[ -z "$local_ok" ]]; then
    log "/health 30s 内未就绪 — 查看日志："
    docker logs --tail 50 "$CONTAINER_NAME"
    die "启动失败"
fi

ok "容器运行中"
echo ""
echo "常用命令："
echo "    docker logs -f $CONTAINER_NAME              # 跟踪日志"
echo "    docker exec -it $CONTAINER_NAME bash        # 进容器"
echo "    bash opencompass-app/scripts/docker-test.sh # 端点测试"
echo "    bash opencompass-app/scripts/docker-stop.sh # 停止 + 清理"