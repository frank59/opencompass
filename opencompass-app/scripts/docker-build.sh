#!/usr/bin/env bash
# docker-build.sh — 构建 opencompass-app 镜像
#
# 用法（在仓库根 /data/src/opencompass）：
#     bash opencompass-app/scripts/docker-build.sh
#
# 镜像名：opencompass-app:develop
# 构建上下文：仓库根 .  （含 opencompass/ 和 opencompass-app/ 两层）
#
# 注意：runtime.txt 含 torch / transformers / sentence_transformers 等重依赖，
# 首次构建约 10-20 分钟。后续若只改 opencompass-app 代码，用
#     docker compose -f opencompass-app/docker-compose.yml build
# 会复用 pip 缓存层（需确保 Dockerfile 各 COPY 顺序稳定）。

set -euo pipefail

# 颜色
RED=$'\033[0;31m'
GRN=$'\033[0;32m'
YLW=$'\033[1;33m'
NC=$'\033[0m'

log() { echo "${YLW}[docker-build]${NC} $*"; }
ok() { echo "${GRN}[docker-build]${NC} $*"; }
die() { echo "${RED}[docker-build] ERROR: $*${NC}" >&2; exit 1; }

# === 路径检查 ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/.." && pwd)"

log "脚本目录:  $SCRIPT_DIR"
log "APP 目录:  $APP_DIR"
log "仓库根:    $REPO_ROOT"

[[ -f "$REPO_ROOT/setup.py" ]] || die "找不到 $REPO_ROOT/setup.py"
[[ -f "$APP_DIR/Dockerfile" ]] || die "找不到 $APP_DIR/Dockerfile"
[[ -f "$REPO_ROOT/requirements/runtime.txt" ]] || die "找不到 $REPO_ROOT/requirements/runtime.txt"
[[ -d "$REPO_ROOT/opencompass" ]] || die "找不到 $REPO_ROOT/opencompass/ 子包目录"

# === docker 检查 ===
command -v docker >/dev/null || die "docker 未安装"
docker info >/dev/null 2>&1 || die "docker daemon 不可达（sudo / docker desktop 未启动？）"

IMAGE_NAME="opencompass-app:develop"

log "构建镜像：$IMAGE_NAME"
log "上下文：  $REPO_ROOT"
log "Dockerfile：$APP_DIR/Dockerfile"
echo ""

cd "$REPO_ROOT"
docker build \
    -t "$IMAGE_NAME" \
    -f "$APP_DIR/Dockerfile" \
    .

ok "构建成功：$IMAGE_NAME"
echo ""
docker images "$IMAGE_NAME" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"
echo ""
ok "下一步："
echo "    bash opencompass-app/scripts/docker-run.sh          # 后台启动"
echo "    bash opencompass-app/scripts/docker-test.sh         # 端点测试"
echo "    bash opencompass-app/scripts/docker-stop.sh         # 停止 + 清理"