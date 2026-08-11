#!/usr/bin/env bash
# scripts/smoke_manual.sh — 手动冒烟测试（开发期回归）。
#
# 流程：
#   1. 启动服务（smoke_bootstrap.py 在 8080 起 uvicorn）
#   2. 等待 /health 就绪
#   3. 顺序执行 17 项端点 + 错误路径冒烟测试
#   4. 关闭服务 + 清理临时数据
#   5. 输出 PASS/FAIL 汇总，exit code = 失败数
#
# 用法：
#   bash scripts/smoke_manual.sh              # 跑全部
#   bash scripts/smoke_manual.sh --keep       # 跑完不清理，便于人工检查
#   bash scripts/smoke_manual.sh t03 t05      # 只跑指定测试

set -eo pipefail

# 注：未启用 -u — 测试函数经常用 ${var:-} 默认值兜底，避免子 shell 异常
#      导致后续变量未赋值而脚本崩溃。

# ---------- 配置 ----------
HOST="127.0.0.1"
PORT="${PORT:-8080}"
BASE="http://${HOST}:${PORT}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OC_DATA_ROOT="${OC_DATA_ROOT:-/tmp/oc-smoke-$$}"
INSTANCE_ID="${INSTANCE_ID:-smoke-test}"
LOG_FILE="${LOG_FILE:-/tmp/uvicorn-smoke.log}"

# 颜色（终端检测）
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YLW=$'\033[0;33m'; CYN=$'\033[0;36m'; NC=$'\033[0m'
else
    RED=''; GRN=''; YLW=''; CYN=''; NC=''
fi

# ---------- 状态 ----------
PID=""
PASS=0
FAIL=0
FAIL_NAMES=()
SELECTED=()  # 用户过滤的测试名
KEEP=0

# ---------- 解析参数 ----------
for arg in "$@"; do
    case "$arg" in
        --keep) KEEP=1 ;;
        -h|--help)
            sed -n '2,15p' "$0"; exit 0 ;;
        t[0-9][0-9]*) SELECTED+=("$arg") ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

should_run() {
    local name="$1"
    if [[ ${#SELECTED[@]} -eq 0 ]]; then return 0; fi
    for s in "${SELECTED[@]}"; do [[ "$s" == "$name" ]] && return 0; done
    return 1
}

# ---------- 工具 ----------
log()    { echo "${CYN}[smoke]${NC} $*"; }
ok()     { echo "${GRN}PASS${NC}  $1"; PASS=$((PASS+1)); }
fail()   { echo "${RED}FAIL${NC}  $1"; FAIL=$((FAIL+1)); FAIL_NAMES+=("$1"); }
section(){ echo; echo "${YLW}━━━ $* ━━━${NC}"; }

# 期望状态码：$1=got, $2=want, $3=name
check_status() {
    if [[ "$1" == "$2" ]]; then
        ok "$3"
    else
        fail "$3 (got=$1 want=$2)"
    fi
}

# JSON 字段提取（python3 单行）
jq_field() {
    local key="$1" body="$2"
    python3 -c "
import json, sys
try:
    print(json.loads(sys.argv[1])$key)
except Exception:
    sys.exit(1)
" "$body"
}

# ---------- 启动 / 清理 ----------
setup_fake_opencompass() {
    # Smoke 专用：假的 opencompass 替身。
    # - 默认任务立即 exit 1（模拟原行为：opencompass 命令不存在 → 子进程失败 → job → FAILED），
    #   让 t05b/t06 在子进程退出后立刻看到终态，避免 timing 抖动。
    # - smoke_cap_* 任务 sleep 10s 保持 slot，给 T16 触发 running-count 409 用。
    # - 用 sh 而非 python：shell 启动 ~5ms 比 python ~100ms 快一个量级。
    # 放在 OC_DATA_ROOT 下，随 KEEP=0 一起清理，不污染全局 PATH。
    local fake_dir="${OC_DATA_ROOT}/.fake-bin"
    mkdir -p "$fake_dir"
    cat > "${fake_dir}/opencompass" <<'SHEOF'
#!/bin/sh
# Smoke fake: smoke_cap_* sleeps 10s (holds slot), others exit 1 immediately.
case "$1" in
    *smoke_cap*) sleep 10; exit 0 ;;
    *) exit 1 ;;
esac
SHEOF
    chmod +x "${fake_dir}/opencompass"
    > /tmp/smoke-fake-global.log  # 清空全局日志
    echo "$fake_dir"
}

start_service() {
    log "启动服务: ${BASE} (OC_DATA_ROOT=${OC_DATA_ROOT})"
    local fake_dir
    fake_dir="$(setup_fake_opencompass)"
    log "fake_dir=${fake_dir} (which opencompass: $(PATH="${fake_dir}:${PATH}" command -v opencompass))"
    cd "$APP_DIR"
    PATH="${fake_dir}:${PATH}" \
    OC_DATA_ROOT="$OC_DATA_ROOT" \
    INSTANCE_ID="$INSTANCE_ID" \
    PORT="$PORT" \
    MAX_CONCURRENT=4 \
    LOG_LEVEL=INFO \
    PYTHONPATH=. \
        python3 scripts/smoke_bootstrap.py >"$LOG_FILE" 2>&1 &
    PID=$!
    cd - >/dev/null

    # 等待 /health 就绪（最长 15s）
    local i
    for i in $(seq 1 30); do
        sleep 0.5
        if curl -sf "${BASE}/health" >/dev/null 2>&1; then
            log "服务就绪（${i} × 0.5s）"
            return 0
        fi
    done
    echo "${RED}服务启动失败 — 日志：${NC}"
    tail -30 "$LOG_FILE"
    exit 1
}

cleanup() {
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        log "关闭服务 (pid=$PID)"
        kill "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    # 释放 8080 端口（防止残留进程占用）
    local leftover
    leftover="$(lsof -ti:${PORT} 2>/dev/null || true)"
    if [[ -n "$leftover" ]]; then
        kill $leftover 2>/dev/null || true
        sleep 1
    fi

    if [[ $KEEP -eq 0 && -d "$OC_DATA_ROOT" ]]; then
        log "清理临时数据 ${OC_DATA_ROOT}"
        rm -rf "$OC_DATA_ROOT"
    fi
}
trap cleanup EXIT INT TERM

# ---------- 测试用例 ----------
t01_health() {
    section "T01: GET /health"
    local code body
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/health")
    body=$(cat /tmp/r.json)
    [[ "$(jq_field '["status"]' "$body")" == "healthy" ]]
    check_status "$code" "200" "T01 /health 200 + status=healthy"
}

t02_workers_free() {
    section "T02: GET /api/v1/workers/me/free"
    local code body
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/workers/me/free")
    body=$(cat /tmp/r.json)
    local avail max
    avail=$(jq_field '["available"]' "$body" 2>/dev/null || echo "")
    max=$(jq_field '["max"]' "$body" 2>/dev/null || echo "")
    if [[ "$avail" == "4" && "$max" == "4" ]]; then
        ok "T02 workers/me/free avail=4 max=4"
    else
        fail "T02 workers/me/free (avail=$avail max=$max body=$body)"
    fi
}

t03_create_job() {
    section "T03: POST /api/v1/jobs (201)"
    JOB_ID="smoke_$$_$(date +%s)"
    local body code
    body=$(cat <<EOF
{
  "job_id": "${JOB_ID}",
  "datasets": [{"abbr": "gsm8k"}],
  "models": [{"type": "opencompass.models.openai_api.OpenAISDK", "path": "qwen", "key": "sk-test"}],
  "created_by": "smoke-test"
}
EOF
)
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X POST "${BASE}/api/v1/jobs" \
        -H "Content-Type: application/json" -d "$body")
    if [[ "$code" == "201" ]]; then
        ok "T03 创建任务 ${JOB_ID}"
    else
        fail "T03 创建任务 (code=$code)"
        cat /tmp/r.json; echo
    fi
}

t04_get_job() {
    section "T04: GET /api/v1/jobs/{id}"
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/jobs/${JOB_ID}")
    check_status "$code" "200" "T04 GET /jobs/{id} 200"
}

t05a_list_owned() {
    section "T05a: GET /api/v1/jobs（本实例过滤）"
    local code body total
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/jobs")
    body=$(cat /tmp/r.json)
    total=$(jq_field '["total"]' "$body" 2>/dev/null || echo "?")
    if [[ "$code" == "200" && "$total" -ge 1 ]]; then
        ok "T05a list owned total>=1 (total=$total)"
    else
        fail "T05a list owned (code=$code total=$total)"
    fi
}

t05b_list_filter_status() {
    section "T05b: GET /api/v1/jobs?status=running"
    # 等 T03 任务到达终态（fake 子进程 ~5ms 内 exit；asyncio 调度 + write_atomic 可能
    # 多花几十毫秒）。轮询 GET /jobs/{id}，status 不是 running/starting 即视为终态。
    local code body total status_now="" i
    for i in $(seq 1 30); do
        body=$(curl -s "${BASE}/api/v1/jobs/${JOB_ID}")
        status_now=$(jq_field '["status"]' "$body" 2>/dev/null || echo "")
        if [[ "$status_now" != "running" && "$status_now" != "starting" && -n "$status_now" ]]; then
            break
        fi
        sleep 0.05
    done
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/jobs?status=running")
    body=$(cat /tmp/r.json)
    total=$(jq_field '["total"]' "$body" 2>/dev/null || echo "?")
    # T03 任务应已到达终态，status=running 过滤应=0
    if [[ "$code" == "200" && "$total" == "0" ]]; then
        ok "T05b status=running → total=0 (job 已到终态 status=$status_now)"
    else
        fail "T05b status filter (code=$code total=$total job_status=$status_now)"
    fi
}

t05c_list_filter_model_path() {
    section "T05c: GET /api/v1/jobs?model_path=qwen"
    local code body total
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/jobs?model_path=qwen")
    body=$(cat /tmp/r.json)
    total=$(jq_field '["total"]' "$body" 2>/dev/null || echo "?")
    if [[ "$code" == "200" && "$total" -ge 1 ]]; then
        ok "T05c model_path=qwen matched (total=$total)"
    else
        fail "T05c model_path filter (code=$code total=$total)"
    fi
}

t05d_list_pagination() {
    section "T05d: GET /api/v1/jobs?all=true 分页 offset=0/1/2/3"
    local total
    total=$(curl -s "${BASE}/api/v1/jobs?all=true" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('total', 0))
except Exception:
    print(0)
")
    # 需要至少 1 个任务
    if [[ "$total" -lt 1 ]]; then
        fail "T05d 准备：需要至少 1 个任务 (total=$total)"
        return
    fi
    local offset items
    for offset in 0 1 2 3; do
        items=$(curl -s "${BASE}/api/v1/jobs?all=true&limit=1&offset=${offset}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
off = int(sys.argv[1])
if off < d['total']:
    print(d['items'][0]['job_id'])
else:
    print('-')
" "$offset")
        if [[ "$offset" -lt "$total" ]]; then
            if [[ -z "$items" || "$items" == "-" || "$items" == "?" ]]; then
                fail "T05d offset=$offset 无 item"; return
            fi
        fi
    done
    ok "T05d 分页 offset=0..3 全部合理（total=$total）"
}

t06_stop_terminal_409() {
    section "T06: POST /stop on terminal job → 409"
    # 等 T03 任务到达终态（与 T05b 同样的 race 问题）。
    local status_now="" i code body
    for i in $(seq 1 30); do
        body=$(curl -s "${BASE}/api/v1/jobs/${JOB_ID}")
        status_now=$(jq_field '["status"]' "$body" 2>/dev/null || echo "")
        if [[ "$status_now" != "running" && "$status_now" != "starting" && -n "$status_now" ]]; then
            break
        fi
        sleep 0.05
    done
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X POST "${BASE}/api/v1/jobs/${JOB_ID}/stop")
    body=$(cat /tmp/r.json)
    if [[ "$code" == "409" ]] && echo "$body" | grep -q "cannot stop"; then
        ok "T06 stop terminal 409 + cannot stop (status=$status_now)"
    else
        fail "T06 stop terminal (code=$code job_status=$status_now)"
    fi
}

t07_delete_terminal_204() {
    section "T07: DELETE /jobs/{id} on terminal → 204"
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X DELETE "${BASE}/api/v1/jobs/${JOB_ID}")
    check_status "$code" "204" "T07 delete terminal 204"
}

t08a_get_missing_404() {
    section "T08a: GET /jobs/missing → 404"
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/jobs/no_such_xyz")
    check_status "$code" "404" "T08a get missing 404"
}

t08b_stop_missing_404() {
    section "T08b: POST /stop/missing → 404"
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X POST "${BASE}/api/v1/jobs/no_such_xyz/stop")
    check_status "$code" "404" "T08b stop missing 404"
}

t09_duplicate_job_409() {
    section "T09: POST 重复 job_id → 409"
    local code
    local body='{"job_id":"dup_test_xyz","datasets":[{"abbr":"gsm8k"}],"models":[{"type":"opencompass.models.openai_api.OpenAISDK","path":"q"}]}'
    curl -s -o /dev/null -X POST "${BASE}/api/v1/jobs" -H "Content-Type: application/json" -d "$body"
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X POST "${BASE}/api/v1/jobs" \
           -H "Content-Type: application/json" -d "$body")
    check_status "$code" "409" "T09 duplicate job_id 409"
}

t10_unknown_model_422() {
    section "T10: POST 未知 model type → 422"
    local code
    local body='{"job_id":"unknown_model_test","datasets":[{"abbr":"gsm8k"}],"models":[{"type":"opencompass.models.NotExistModel","path":"q"}]}'
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X POST "${BASE}/api/v1/jobs" \
           -H "Content-Type: application/json" -d "$body")
    check_status "$code" "422" "T10 unknown model 422"
}

t11_cross_instance_403() {
    section "T11: 跨实例 stop → 403"
    # 注入一个 OTHER-INSTANCE 的状态文件
    local state_dir="${OC_DATA_ROOT}/workspace/state/jobs"
    mkdir -p "$state_dir"
    cat > "${state_dir}/manual_fake.json" <<EOF
{"job_id":"manual_fake","status":"running","instance_id":"OTHER-INSTANCE","datasets":[],"models":[],"config_path":"/x","work_dir":"/y","created_at":"2026-08-11T00:00:00Z","created_by":"smoke"}
EOF
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X POST "${BASE}/api/v1/jobs/manual_fake/stop")
    if [[ "$code" == "403" ]]; then
        ok "T11 跨实例 stop 403"
    else
        fail "T11 跨实例 stop (code=$code)"
    fi
    # 验证 GET 可读（list_all=true 可见，本实例过滤不可见）
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/jobs/manual_fake")
    check_status "$code" "200" "T11b GET 跨实例任务仍可读 200"
}

t12_health_final() {
    section "T12: 健康检查 final"
    local code body status
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/health")
    body=$(cat /tmp/r.json)
    status=$(jq_field '["status"]' "$body" 2>/dev/null || echo "?")
    if [[ "$code" == "200" && "$status" == "healthy" ]]; then
        ok "T12 health final healthy"
    else
        fail "T12 health final (code=$code status=$status)"
    fi
}

t13_log_no_panic() {
    section "T13: 服务日志无 panic/Traceback"
    if [[ -f "$LOG_FILE" ]]; then
        local panics
        panics=$(grep -cE "Traceback|panic:|Unhandled exception" "$LOG_FILE" || true)
        if [[ "$panics" == "0" ]]; then
            ok "T13 log clean (no panic/traceback)"
        else
            fail "T13 log 含 $panics 处异常"
        fi
    else
        fail "T13 log 文件不存在: $LOG_FILE"
    fi
}

t14_patch_capacity_success() {
    section "T14: PATCH /api/v1/workers/me/capacity 200"
    local code body new_max
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X PATCH "${BASE}/api/v1/workers/me/capacity" \
        -H "Content-Type: application/json" -d '{"max_concurrent": 8}')
    body=$(cat /tmp/r.json)
    new_max=$(jq_field '["max_concurrent"]' "$body" 2>/dev/null || echo "")
    if [[ "$code" == "200" && "$new_max" == "8" ]]; then
        ok "T14 PATCH capacity 200 + max=8"
    else
        fail "T14 PATCH capacity (code=$code max=$new_max body=$body)"
    fi
    # 校验 /workers/me/free 立即反映新值（先抓 body 再用 jq_field，避免 stdin 传不到 $2）
    local free_body free_max
    free_body=$(curl -s "${BASE}/api/v1/workers/me/free")
    free_max=$(jq_field '["max"]' "$free_body" 2>/dev/null || echo "")
    if [[ "$free_max" == "8" ]]; then
        ok "T14b /workers/me/free 立即反映新 max=8"
    else
        fail "T14b /workers/me/free max=$free_max (期望 8)"
    fi
}

t15_patch_capacity_zero_422() {
    section "T15: PATCH /me/capacity max=0 → 422"
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X PATCH "${BASE}/api/v1/workers/me/capacity" \
        -H "Content-Type: application/json" -d '{"max_concurrent": 0}')
    check_status "$code" "422" "T15 PATCH capacity 0 → 422"
}

t16_patch_capacity_below_running_409() {
    section "T16: PATCH /me/capacity < running → 409"
    # Pydantic gt=0 在 max=0 时返 422；这里要用 >0 但 < running_count 才会走业务 409。
    # 先把上限提到 8（容纳 2 个任务），再并发 POST 2 个任务占住 slot。
    curl -s -o /dev/null -X PATCH "${BASE}/api/v1/workers/me/capacity" \
        -H "Content-Type: application/json" -d '{"max_concurrent": 8}'
    local job_a="smoke_cap_a_$$"
    local job_b="smoke_cap_b_$$"
    curl -s -o /dev/null -X POST "${BASE}/api/v1/jobs" -H "Content-Type: application/json" \
        -d "{\"job_id\":\"${job_a}\",\"datasets\":[{\"abbr\":\"gsm8k\"}],\"models\":[{\"type\":\"opencompass.models.openai_api.OpenAISDK\",\"path\":\"q\"}]}"
    curl -s -o /dev/null -X POST "${BASE}/api/v1/jobs" -H "Content-Type: application/json" \
        -d "{\"job_id\":\"${job_b}\",\"datasets\":[{\"abbr\":\"gsm8k\"}],\"models\":[{\"type\":\"opencompass.models.openai_api.OpenAISDK\",\"path\":\"q\"}]}"
    # 轮询 running >= 2（子进程退出后会 release slot，窗口可能很短）
    local i running="" free_body
    for i in $(seq 1 20); do
        free_body=$(curl -s "${BASE}/api/v1/workers/me/free")
        running=$(jq_field '["running"]' "$free_body" 2>/dev/null || echo "")
        if [[ "$running" -ge 2 ]]; then break; fi
        sleep 0.05
    done
    if [[ "$running" -lt 2 ]]; then
        fail "T16 准备失败: running=$running (期望 >=2，可能子进程太快退出)"
        return
    fi
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" -X PATCH "${BASE}/api/v1/workers/me/capacity" \
        -H "Content-Type: application/json" -d '{"max_concurrent": 1}')
    if [[ "$code" == "409" ]]; then
        ok "T16 PATCH capacity 1 (running=$running) → 409"
    else
        fail "T16 PATCH capacity (code=$code body=$(cat /tmp/r.json))"
    fi
}

t17_recovery_e2e() {
    section "T17: 残留状态文件可被 GET 读取"
    # 注入一个 starting 残留
    local state_dir="${OC_DATA_ROOT}/workspace/state/jobs"
    mkdir -p "$state_dir"
    cat > "${state_dir}/smoke_residual.json" <<EOF
{"job_id":"smoke_residual","status":"starting","instance_id":"${INSTANCE_ID}","pid":null,"datasets":[],"models":[],"config_path":"/x","work_dir":"/y","created_at":"2026-08-11T00:00:00Z"}
EOF
    local code
    code=$(curl -s -o /tmp/r.json -w "%{http_code}" "${BASE}/api/v1/jobs/smoke_residual")
    if [[ "$code" == "200" ]]; then
        ok "T17 残留状态文件可被 GET（recover 验证留给集成测试）"
    else
        fail "T17 残留 GET (code=$code)"
    fi
}

# ---------- 主流程 ----------
run_tests() {
    local t
    for t in t01_health t02_workers_free t03_create_job t04_get_job \
             t05a_list_owned t05b_list_filter_status t05c_list_filter_model_path \
             t05d_list_pagination t06_stop_terminal_409 t07_delete_terminal_204 \
             t08a_get_missing_404 t08b_stop_missing_404 t09_duplicate_job_409 \
             t10_unknown_model_422 t11_cross_instance_403 t12_health_final \
             t13_log_no_panic t14_patch_capacity_success t15_patch_capacity_zero_422 \
             t16_patch_capacity_below_running_409 t17_recovery_e2e; do
        if should_run "$t"; then
            "$t"
        fi
    done
}

start_service
run_tests

# ---------- 汇总 ----------
echo
echo "${YLW}━━━━━━━━ 冒烟测试汇总 ━━━━━━━━${NC}"
echo "PASS: ${GRN}${PASS}${NC}    FAIL: ${RED}${FAIL}${NC}"
if [[ $FAIL -gt 0 ]]; then
    echo "${RED}失败项：${FAIL_NAMES[*]}${NC}"
    exit 1
fi
echo "${GRN}全部通过 ✅${NC}"
exit 0