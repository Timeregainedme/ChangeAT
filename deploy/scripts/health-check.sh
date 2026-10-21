#!/usr/bin/env bash
#
# 生产巡检脚本。
#
# 为什么需要它：
# 切流后系统有 4 个常驻进程（nginx / Python API / Celery / Go），
# 任何一个挂掉都只表现为「某个页面转圈」，没有人会主动去 journalctl 翻。
# 之前发现的 /health 返回 HTML、404 不走信封这类问题，也都是「看起来正常」的，
# 靠肉眼巡检根本发现不了。
#
# 设计原则：
# 1. **只读**：不重启、不修改任何状态，可以随时手动跑；
# 2. **默认静默**：一切正常时只输出一行 OK；异常时才逐项列出 —— 
#    这样接 cron/timer 时不会每天产生几十条「正常」日志；
# 3. **失败即非零退出**：便于 systemd/cron 判定；
# 4. 不依赖 Python/Go 环境，只用 curl、systemctl、awk。
#
# 用法：
#   ./health-check.sh            # 人看：总是输出摘要
#   ./health-check.sh --quiet    # 机器看：仅异常时输出
#
# 退出码：0 全部正常 / 1 有异常 / 2 脚本自身错误（如缺 curl）

set -uo pipefail

QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

FAILURES=()
WARNINGS=()

# --- 可调阈值 ---
DISK_WARN_PCT=85
MEM_WARN_PCT=90
HTTP5XX_WARN_COUNT=20   # 最近 1000 条访问日志里 5xx 的上限

ok()   { [[ $QUIET -eq 0 ]] && printf '  ✓ %s\n' "$1"; return 0; }
fail() { FAILURES+=("$1"); [[ $QUIET -eq 0 ]] && printf '  ✗ %s\n' "$1"; return 0; }
warn() { WARNINGS+=("$1"); [[ $QUIET -eq 0 ]] && printf '  ! %s\n' "$1"; return 0; }

# ---------- 1. systemd 单元 ----------
[[ $QUIET -eq 0 ]] && echo "[服务状态]"
for unit in nginx dyeingtime-api dyeingtime-celery dyeingtime-go; do
    state=$(systemctl is-active "$unit" 2>/dev/null || true)
    if [[ "$state" == "active" ]]; then
        ok "$unit active"
    else
        fail "$unit 状态异常：${state:-unknown}"
    fi
done

# ---------- 2. 探针（含响应格式校验） ----------
[[ $QUIET -eq 0 ]] && echo "[探针]"

# /health → Go，必须返回 JSON 信封而不是 HTML。
# 这条曾经坏过：/health 落进 SPA fallback，返回 200 + index.html，
# 外部探活永远「健康」。所以这里既查状态码也查内容形态。
# 一次请求同时拿状态码与 body：先看状态码，再判断内容形态。
# 分开判断的原因：502 时 Nginx 返回的是自己的 HTML 错误页，
# 若只看 body 会把「上游挂了」误报成「配置回退到 SPA」。
health_raw=$(curl -s -w '\n__CODE__%{http_code}' --max-time 5 \
    --resolve tim.run.place:443:127.0.0.1 https://tim.run.place/health 2>/dev/null || true)
health_code="${health_raw##*__CODE__}"
health_body="${health_raw%$'\n'__CODE__*}"
if [[ "$health_code" != "200" ]]; then
    fail "/health 状态码 ${health_code:-无}（Go 可能已挂或 Nginx 指向错误）"
elif [[ "$health_body" == *'"code":200'* ]]; then
    ok "/health 返回信封"
elif [[ "$health_body" == *'<!doctype html'* || "$health_body" == *'<html'* ]]; then
    fail "/health 返回了 HTML（探针配置回退到 SPA fallback）"
else
    fail "/health 响应异常：${health_body:0:80}"
fi

ready_body=$(curl -s --max-time 5 --resolve tim.run.place:443:127.0.0.1 https://tim.run.place/api/v1/ready 2>/dev/null || true)
if [[ "$ready_body" == *'"database":"ok"'* ]]; then
    ok "/api/v1/ready 数据库连通"
elif [[ -z "$ready_body" ]]; then
    fail "/api/v1/ready 无响应（Go 可能已挂）"
else
    fail "/api/v1/ready 异常：${ready_body:0:80}"
fi

py_body=$(curl -s --max-time 5 http://127.0.0.1:8000/health 2>/dev/null || true)
if [[ "$py_body" == *'"status":"ok"'* ]]; then
    ok "Python /health 正常"
else
    fail "Python 不可达（127.0.0.1:8000）"
fi

# ---------- 3. 资源 ----------
[[ $QUIET -eq 0 ]] && echo "[资源]"
disk_pct=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')
if [[ -n "$disk_pct" && "$disk_pct" -ge "$DISK_WARN_PCT" ]]; then
    warn "磁盘使用 ${disk_pct}%（阈值 ${DISK_WARN_PCT}%）"
else
    ok "磁盘使用 ${disk_pct}%"
fi

mem_pct=$(free | awk 'NR==2 {printf "%d", ($3/$2)*100}')
if [[ -n "$mem_pct" && "$mem_pct" -ge "$MEM_WARN_PCT" ]]; then
    warn "内存使用 ${mem_pct}%（阈值 ${MEM_WARN_PCT}%）"
else
    ok "内存使用 ${mem_pct}%"
fi

go_pid=$(pgrep -f "/srv/dyeingtime-go/api" | head -1 || true)
if [[ -n "$go_pid" ]]; then
    go_rss_mb=$(ps -o rss= -p "$go_pid" | awk '{printf "%.1f", $1/1024}')
    ok "Go RSS ${go_rss_mb} MB"
else
    fail "找不到 Go 进程"
fi

# ---------- 4. 错误率 ----------
[[ $QUIET -eq 0 ]] && echo "[错误率]"
if [[ -r /var/log/nginx/dyeingtime.access.log ]]; then
    # 最近 1000 条里 5xx 的数量（跳过无法判定的行）
    total=$(tail -1000 /var/log/nginx/dyeingtime.access.log 2>/dev/null | wc -l | tr -d ' ')
    count5xx=$(tail -1000 /var/log/nginx/dyeingtime.access.log 2>/dev/null | awk '$9 ~ /^5/ {c++} END {print c+0}')
    if [[ "${count5xx:-0}" -ge "$HTTP5XX_WARN_COUNT" ]]; then
        warn "最近 ${total} 条请求中 5xx 有 ${count5xx} 条"
    else
        ok "5xx 比例正常（${count5xx}/${total}）"
    fi
else
    warn "无权限读取 nginx 访问日志（需要 sudo）"
fi

# Go / Python 的 panic / traceback
go_panics=$(journalctl -u dyeingtime-go --since "1 hour ago" --no-pager 2>/dev/null | grep -c "panic recovered" || true)
[[ "${go_panics:-0}" -gt 0 ]] && fail "Go 近 1 小时有 ${go_panics} 次 panic"

py_errors=$(journalctl -u dyeingtime-api --since "1 hour ago" --no-pager 2>/dev/null | grep -cE "ERROR|Traceback" || true)
[[ "${py_errors:-0}" -gt 0 ]] && warn "Python 近 1 小时有 ${py_errors} 条 ERROR/Traceback"

# ---------- 汇总 ----------
if [[ ${#FAILURES[@]} -eq 0 && ${#WARNINGS[@]} -eq 0 ]]; then
    [[ $QUIET -eq 0 ]] && echo
    echo "OK $(date -u '+%Y-%m-%dT%H:%M:%SZ') 全部正常"
    exit 0
fi

echo
[[ ${#FAILURES[@]} -gt 0 ]] && echo "FAIL(${#FAILURES[@]})"
for f in "${FAILURES[@]}"; do echo "  - $f"; done
[[ ${#WARNINGS[@]} -gt 0 ]] && echo "WARN(${#WARNINGS[@]})"
for w in "${WARNINGS[@]}"; do echo "  - $w"; done

[[ ${#FAILURES[@]} -gt 0 ]] && exit 1
exit 0
