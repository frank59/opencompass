#!/usr/bin/env bash
# diag.sh — 在远程机器上跑这个，把输出贴回来
echo "===[1] 仓库根 ls==="
ls -la
echo
echo "===[2] opencompass/ 内容==="
ls opencompass/ 2>&1 | head -25
echo
echo "===[3] opencompass-app/ 内容==="
ls opencompass-app/
echo
echo "===[4] find setup.py ==="
find . -name 'setup.py' -not -path '*/node_modules/*' 2>/dev/null | grep -v site-packages | head -10
echo
echo "===[5] find pyproject.toml ==="
find . -maxdepth 3 -name 'pyproject.toml' -not -path '*/node_modules/*' 2>/dev/null
echo
echo "===[6] git submodule status ==="
git submodule status 2>&1 | head -10
echo
echo "===[7] git remote -v ==="
git remote -v
echo
echo "===[8] git branch -vv ==="
git branch -vv
echo
echo "===[9] git log --oneline -5 ==="
git log --oneline -5
echo
echo "===[10] git status --short ==="
git status --short | head -20
echo
echo "===[11] 是否有 Dockerfile / 脚本就位 ==="
ls -la opencompass-app/Dockerfile opencompass-app/docker-compose.yml \
    opencompass-app/scripts/docker-build.sh 2>&1