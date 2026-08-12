#!/usr/bin/env bash
# docker-test.sh — 容器内 opencompass-app 端点黑盒测试
#
# 与 smoke_manual.sh 的区别：本脚本不依赖 fake opencompass，
# 容器内子进程直接调用真 OC（OC 可能因缺 GPU/API key 跑不完任务，
# 但这不影响端点契约验证 — 我们只验 API 响应码 + JSON 结构）。
#
# 用法（在仓库根 /data/src/opencompass）：
#     bash opencompass-app/scripts/docker-test.sh
#     PORT=8081 bash opencompass-app/scripts/docker-test.sh
#
# 端点覆盖（10 个）：
#     MVP (4): POST /jobs, GET /jobs/{id}, GET /workers/me/free, GET /health
#     Phase 2 (3): GET /jobs (list), POST /jobs/{id}/stop, DELETE /jobs/{id}
#     Phase 3 (2): PATCH /workers/me/capacity, /health 503 gate (recover 期间)
#     Phase 4 (1): GET /jobs/{id}/log（分页 + tail）

set -euo pipefail

RED=$'\033[0;31m'
GRN=$'\033[0;32m'
YLW=$'\033[1;33m'
NC=$'\033[0m'

log() { echo "${YLW}[docker-test]${NC} $*"; }
ok() { PASS=$((PASS+1)); echo "  ${GRN}PASS${NC}  $*"; }
fail() { FAIL=$((FAIL+1)); echo "  ${RED}FAIL${NC}  $*"; }

# 自动检测可达的 BASE URL：
# - HOST_IP 环境变量优先（明确指定宿主机外部 IP）
# - 否则尝试宿主机外部 IPv4（ip route 源 IP，避开 docker bridge 172.17.x.x）
# - 最后回退到 localhost（如果宿主机 iptables 正常转 loopback）
# 注：有些 Linux 上 docker iptables DOCKER 链对 lo 接口不生效，所以不能直接
# 用 127.0.0.1。从宿主机的物理网卡 IP 访问，docker 端口转发一定生效。
detect_base() {
    local port="${PORT:-8080}"
    if [[ -n "${HOST_IP:-}" ]]; then
        echo "http://${HOST_IP}:${port}"
        return
    fi
    # ip route get 默认路由的源 IP（通常是物理网卡，不是 docker bridge）
    local ip
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
    if [[ -n "$ip" && "$ip" != "127.0.0.1" ]]; then
        echo "http://${ip}:${port}"
        return
    fi
    # 最后回退 localhost
    echo "http://127.0.0.1:${port}"
}
BASE=$(detect_base)
log "测试 BASE: $BASE"
PASS=0
FAIL=0

# jq 可选，没有就用 python
jq_field() {
    local key="$1" body="$2"
    if command -v jq >/dev/null 2>&1; then
        echo "$body" | jq -r "$key" 2>/dev/null || echo "?"
    else
        echo "$body" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for k in '$key'.lstrip('[').rstrip(']').split(']['):
        d = d[k.strip('\"')]
    print(d if d is not None else 'null')
except Exception:
    print('?')
"
    fi
}

# === T0: /health 应已就绪 ===
log "=== T0: GET /health ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' "$BASE/health")
body=$(cat /tmp/r.json)
status=$(jq_field '["status"]' "$body" 2>/dev/null || echo "?")
if [[ "$code" == "200" && "$status" == "healthy" ]]; then
    ok "T0 /health 200 + status=healthy"
else
    fail "T0 /health (code=$code status=$status body=$body)"
    log "服务未就绪，跳过剩余测试"
    echo ""
    echo "${RED}FAIL: $FAIL  PASS: $PASS${NC}"
    exit 1
fi

# === T1: GET /workers/me/free ===
log "=== T1: GET /api/v1/workers/me/free ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' "$BASE/api/v1/workers/me/free")
body=$(cat /tmp/r.json)
max_val=$(jq_field '["max"]' "$body" 2>/dev/null || echo "?")
if [[ "$code" == "200" && "$max_val" =~ ^[0-9]+$ ]]; then
    ok "T1 workers/me/free 200 + max=$max_val"
else
    fail "T1 workers/me/free (code=$code body=$body)"
fi

# === T2: POST /jobs (创建任务) ===
# 注意：model.type 必须是 ModelWhitelist 接受的格式 "opencompass.models.<ClassName>"
# （看 app/core/model_whitelist.py 的 found.add(f"opencompass.models.{obj.__name__}")）。
# Phase 2 测试用 mock whitelist 能用 "opencompass.models.openai_api.OpenAISDK" 带子模块路径，
# 但运行时真实 whitelist 不含子模块，所以必须用短名路径。
#
# 这个测试验证 API 端点契约（201/202 返回 job_id），不验证 OC 子进程能跑通任务。
# 容器内没 GPU / API key，子进程跑模型调用会失败，但不影响 T2 通过。
log "=== T2: POST /api/v1/jobs (201) ==="
JOB_ID="docker_test_$(date +%s)_$$"
read -r -d '' BODY <<JSON || true
{
  "job_id": "${JOB_ID}",
  "datasets": [{"abbr": "gsm8k"}],
  "models": [{
    "type": "opencompass.models.OpenAISDK",
    "path": "qwen",
    "key": "EMPTY",
    "openai_api_base": "https://example.invalid/v1"
  }]
}
JSON
code=$(curl -s -o /tmp/r.json -w '%{http_code}' -X POST "$BASE/api/v1/jobs" \
    -H 'content-type: application/json' \
    -d "$BODY")
resp_body=$(cat /tmp/r.json)
if [[ "$code" == "201" || "$code" == "202" ]]; then
    ok "T2 POST /jobs (code=$code, job_id=$JOB_ID)"
else
    fail "T2 POST /jobs (code=$code body=$resp_body)"
fi

# === T3: GET /jobs/{id} ===
log "=== T3: GET /api/v1/jobs/{id} ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' "$BASE/api/v1/jobs/$JOB_ID")
body=$(cat /tmp/r.json)
got_status=$(jq_field '["status"]' "$body" 2>/dev/null || echo "?")
if [[ "$code" == "200" && -n "$got_status" && "$got_status" != "?" ]]; then
    ok "T3 GET /jobs/{id} 200 + status=$got_status"
else
    fail "T3 GET /jobs/{id} (code=$code body=$body)"
fi

# === T10: GET /jobs/{id}/log (Phase 4) ===
# 在 DELETE 之前测 — state 存在，log_path 也在 state 里。子进程可能已写少量
# 日志到 opencompass.log，也可能因为没 GPU/API key 已经退出（文件可能为空），
# 这都不影响端点契约验证：200 + 合法 JSON 结构。
log "=== T10: GET /api/v1/jobs/{id}/log ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' "$BASE/api/v1/jobs/$JOB_ID/log")
body=$(cat /tmp/r.json)
log_path=$(jq_field '["log_path"]' "$body" 2>/dev/null || echo "")
total=$(jq_field '["total_lines"]' "$body" 2>/dev/null || echo "?")
returned=$(jq_field '["returned_lines"]' "$body" 2>/dev/null || echo "?")
if [[ "$code" == "200" && "$log_path" == *"opencompass.log" ]]; then
    ok "T10 GET /log 200 + log_path contains opencompass.log (total=$total returned=$returned)"
else
    fail "T10 GET /log (code=$code log_path=$log_path body=$body)"
fi

# === T10b: tail=true & limit ===
log "=== T10b: GET /log?tail=true&limit=10 ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' "$BASE/api/v1/jobs/$JOB_ID/log?tail=true&limit=10")
body=$(cat /tmp/r.json)
returned=$(jq_field '["returned_lines"]' "$body" 2>/dev/null || echo "?")
start=$(jq_field '["start_line"]' "$body" 2>/dev/null || echo "?")
if [[ "$code" == "200" ]]; then
    ok "T10b /log tail=10 200 + start=$start returned=$returned"
else
    fail "T10b /log tail=10 (code=$code body=$body)"
fi

# === T10c: GET /log 未知 job → 404 ===
log "=== T10c: GET /log unknown job → 404 ==="
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/v1/jobs/no_such_job_xyz/log")
if [[ "$code" == "404" ]]; then
    ok "T10c /log unknown job 404"
else
    fail "T10c /log unknown job (expected 404 got $code)"
fi

# === T4: GET /jobs (列表，本实例过滤) ===
log "=== T4: GET /api/v1/jobs (list owned) ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' "$BASE/api/v1/jobs")
body=$(cat /tmp/r.json)
total=$(jq_field '["total"]' "$body" 2>/dev/null || echo "?")
if [[ "$code" == "200" && "$total" =~ ^[0-9]+$ && "$total" -ge 1 ]]; then
    ok "T4 GET /jobs 200 + total=$total"
else
    fail "T4 GET /jobs (code=$code total=$total)"
fi

# === T5: PATCH /me/capacity (200) ===
log "=== T5: PATCH /api/v1/workers/me/capacity 200 ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' -X PATCH "$BASE/api/v1/workers/me/capacity" \
    -H 'content-type: application/json' -d '{"max_concurrent": 8}')
body=$(cat /tmp/r.json)
new_max=$(jq_field '["max_concurrent"]' "$body" 2>/dev/null || echo "")
if [[ "$code" == "200" && "$new_max" == "8" ]]; then
    ok "T5 PATCH capacity 200 + max=8"
else
    fail "T5 PATCH capacity (code=$code max=$new_max body=$body)"
fi

# === T6: PATCH /me/capacity max=0 → 422 ===
log "=== T6: PATCH max_concurrent=0 → 422 ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' -X PATCH "$BASE/api/v1/workers/me/capacity" \
    -H 'content-type: application/json' -d '{"max_concurrent": 0}')
if [[ "$code" == "422" ]]; then
    ok "T6 PATCH capacity 0 → 422"
else
    fail "T6 PATCH capacity (expected 422 got $code)"
fi

# === T7: POST /jobs/{id}/stop ===
log "=== T7: POST /api/v1/jobs/{id}/stop ==="
# T2 任务可能还在 starting/running — stop 应该返回 202（accepted）
# 也可能子进程已经退出变成终态 — stop 应返 409
# 两种结果都算"stop 端点正确响应"
code=$(curl -s -o /tmp/r.json -w '%{http_code}' -X POST "$BASE/api/v1/jobs/$JOB_ID/stop")
body=$(cat /tmp/r.json)
if [[ "$code" == "202" ]]; then
    ok "T7 stop 202 (running → cancelling)"
elif [[ "$code" == "409" ]]; then
    ok "T7 stop 409 (already terminal, expected)"
else
    fail "T7 stop (unexpected code=$code body=$body)"
fi

# === T8: DELETE /jobs/{id} ===
log "=== T8: DELETE /api/v1/jobs/{id} ==="
# 等任务到终态（轮询最多 10s）
terminal=""
for i in $(seq 1 20); do
    body=$(curl -s "$BASE/api/v1/jobs/$JOB_ID")
    s=$(jq_field '["status"]' "$body" 2>/dev/null || echo "")
    if [[ "$s" != "running" && "$s" != "starting" && "$s" != "cancelling" && -n "$s" ]]; then
        terminal="$s"; break
    fi
    sleep 0.5
done
code=$(curl -s -o /tmp/r.json -w '%{http_code}' -X DELETE "$BASE/api/v1/jobs/$JOB_ID")
if [[ "$code" == "204" ]]; then
    ok "T8 DELETE 204 (job was $terminal)"
elif [[ "$code" == "409" ]]; then
    fail "T8 DELETE 409 (job not terminal: $terminal)"
else
    fail "T8 DELETE (unexpected code=$code)"
fi

# === T9: GET /health final (recover 后应返 200) ===
log "=== T9: GET /health final ==="
code=$(curl -s -o /tmp/r.json -w '%{http_code}' "$BASE/health")
status=$(jq_field '["status"]' "$(cat /tmp/r.json)" 2>/dev/null || echo "?")
if [[ "$code" == "200" && "$status" == "healthy" ]]; then
    ok "T9 /health final 200 healthy"
else
    fail "T9 /health final (code=$code status=$status)"
fi

# === 汇总 ===
echo ""
echo "${YLW}━━━━━━━━ 端点测试汇总 ━━━━━━━━${NC}"
echo "PASS: ${GRN}${PASS}${NC}    FAIL: ${RED}${FAIL}${NC}"
if [[ $FAIL -gt 0 ]]; then
    echo "${RED}失败项见上方${NC}"
    exit 1
fi
echo "${GRN}全部通过 ✅${NC}"