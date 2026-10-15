#!/usr/bin/env bash
# 本地全栈启动（dev）。用法：./scripts/dev.sh
# 只做三件事：检查 venv、起后端、起前端。不依赖外部服务（DeepSeek key 在 backend/.env）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/Scripts/python.exe"

say() { printf '\033[1;36m[dev]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[dev] 错误: %s\033[0m\n' "$*" >&2; exit 1; }

[ -x "$PY" ] || die "找不到 $PY —— 仓库根需要 .venv（python -m venv .venv）"

say "venv: $PY"

# ---- 后端（8000）----
# 必须在 backend/ 下跑：api.api 是相对 import，且 data/ 用相对路径
say "启动后端 http://127.0.0.1:8000 ..."
( cd "$ROOT/backend" && exec "$PY" -m uvicorn api.api:app --reload --port 8000 ) &
BACK_PID=$!

# ---- 前端（5173）----
say "启动前端 http://127.0.0.1:5173 ..."
( cd "$ROOT/front" && exec npm run dev ) &
FRONT_PID=$!

trap 'say "收到中断，正在停下..."; kill $BACK_PID $FRONT_PID 2>/dev/null || true; wait 2>/dev/null || true' INT TERM

say "后端 pid=$BACK_PID  前端 pid=$FRONT_PID   Ctrl-C 全停"
say "验证："
say "  curl -s --noproxy '*' http://127.0.0.1:8000/health"
say "  （本机有 http_proxy，不加 --noproxy 可能拿到 502）"
wait
