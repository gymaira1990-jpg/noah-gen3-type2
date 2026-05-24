#!/usr/bin/env bash
# 搜索工具链健康看板
# 测试所有搜索组件，记录耗时和成功率，输出 JSON
# 用法: bash search_health.sh           # 采集一次
#        bash search_health.sh cron     # 采集+追加历史

set -euo pipefail
DATA_DIR="${HEALTH_DATA_DIR:-./data/search-health}"
mkdir -p "$DATA_DIR"

NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OUTPUT="$DATA_DIR/latest.json"
HISTORY="$DATA_DIR/history.csv"

# 配置（通过环境变量覆盖）
CDP_HOST="${CDP_HOST:-127.0.0.1}"
CDP_PORT="${CDP_PORT:-9222}"

# ── 辅助: 测耗时(秒) ──
_timer() {
    local start end
    start=$(date +%s%N)
    eval "$*" >/dev/null 2>/dev/null
    end=$(date +%s%N)
    awk "BEGIN { printf \"%.3f\", ($end - $start) / 1000000000 }"
}

report=$(cat << JSON
{
  "timestamp": "$NOW",
  "components": {
JSON
)

# 1. Edge CDP
ed_ok="false"; ed_time="0"
if t=$(_timer curl -sf --max-time 5 "http://${CDP_HOST}:${CDP_PORT}/json/version"); then
    ed_ok="true"
    ed_time="$t"
fi
report+=$(cat << JSON
    "edge_cdp": {"alive": $ed_ok, "latency_s": $ed_time},

JSON
)

# 2. 本地端口（示例）
report+=$(cat << JSON
    "localhost": {"alive": true, "latency_s": 0}
  },
  "summary": {
    "total": 1,
JSON
)

# ── 汇总 ──
alive_count=0
[ "$ed_ok" = "true" ] && alive_count=$((alive_count + 1))
report=$(echo "$report" | sed '$s/}$//')
report+=$(cat << JSON
    "alive": $alive_count
  }
}
JSON
)

echo "$report" | python3 -m json.tool 2>/dev/null || echo "$report"
echo "$report" > "$OUTPUT"

# ── 追加历史 ──
if [ "${1:-}" = "cron" ]; then
    echo "$NOW,$ed_ok,$ed_time" >> "$HISTORY"
    tail -1000 "$HISTORY" > "${HISTORY}.tmp" && mv "${HISTORY}.tmp" "$HISTORY"
fi
