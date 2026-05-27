#!/usr/bin/env bash
# arc — 诺亚核心 CLI 快捷入口
# 安装: sudo ln -sf <project_root>/arc.sh /usr/local/bin/arc
set -e
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"
exec "$SCRIPT_DIR/.venv/bin/python" -m core "$@"
