#!/usr/bin/env bash
# docker-stop.sh — 停止 + 删除 opencompass-app 容器
#
# 用法：
#     bash opencompass-app/scripts/docker-stop.sh
#     bash opencompass-app/scripts/docker-stop.sh --purge   # 连同镜像一起删
#
# 数据卷 /data/opencompass 不在清理范围（用户数据）

set -euo pipefail

RED=$'\033[0;31m'
GRN=$'\033[0;32m'
YLW=$'\033[1;33m'
NC=$'\033[0m'

log() { echo "${YLW}[docker-stop]${NC} $*"; }
ok() { echo "${GRN}[docker-stop]${NC} $*"; }

CONTAINER_NAME="opencompass-app"
IMAGE_NAME="opencompass-app:develop"

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    log "停止容器: $CONTAINER_NAME"
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    log "删除容器: $CONTAINER_NAME"
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    ok "容器已清理"
else
    log "容器 $CONTAINER_NAME 不存在，跳过"
fi

if [[ "${1:-}" == "--purge" ]]; then
    if docker images --format '{{.Repository}}:{{.Tag}}' | grep -qx "$IMAGE_NAME"; then
        log "删除镜像: $IMAGE_NAME"
        docker rmi "$IMAGE_NAME"
        ok "镜像已删除"
    else
        log "镜像 $IMAGE_NAME 不存在，跳过"
    fi
fi

ok "完成"