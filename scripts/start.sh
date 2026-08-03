#!/usr/bin/env bash
# Mochi 本地开发一键启动：Ollama（如已安装）→ sidecar（8199）→ 前端（1420）
#
# 用法：
#   ./scripts/start.sh            # 启动全部（已运行的服务自动跳过）
#   ./scripts/start.sh --web-only # 只启动前端（sidecar/Ollama 自行管理时用）
#
# 日志输出到 logs/（已被 .gitignore 忽略）。停止见 scripts/stop.sh。
# 注意：echo 中变量后紧跟全角字符时必须用 ${VAR} 花括号形式（bash 多字节解析坑）。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

# uv 默认安装位置可能不在 PATH
export PATH="$HOME/.local/bin:$PATH"

OLLAMA_PORT=11434
SIDECAR_PORT=8199
WEB_PORT=1420

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

port_in_use() {
  lsof -ti :"$1" >/dev/null 2>&1
}

http_ok() {
  curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$1$2"
}

wait_http() { # wait_http <port> <path> <秒数> <名称>
  local port=$1 path=$2 timeout=$3 name=$4
  for _ in $(seq 1 "$timeout"); do
    if http_ok "$port" "$path"; then
      echo "  ✓ ${name} 就绪：http://127.0.0.1:${port}${path}"
      return 0
    fi
    sleep 1
  done
  echo "  ✗ ${name} 启动超时，请查看 logs/ 下对应日志"
  return 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------

for tool in uv pnpm node; do
  if ! command_exists "$tool"; then
    echo "✗ 缺少依赖：${tool}（安装指引见 README「开发环境准备」）"
    exit 1
  fi
done

if [ ! -d "${ROOT}/node_modules" ]; then
  echo "→ 首次运行，安装 JS 依赖…"
  (cd "$ROOT" && pnpm install)
fi

WEB_ONLY=false
[ "${1:-}" = "--web-only" ] && WEB_ONLY=true

# ---------------------------------------------------------------------------
# 1. Ollama（可选：未安装则走试用模式/云端 Key，不影响启动）
# ---------------------------------------------------------------------------

if [ "$WEB_ONLY" = false ]; then
  if command_exists ollama; then
    if http_ok "$OLLAMA_PORT" /api/version; then
      echo "✓ Ollama 已在运行：127.0.0.1:${OLLAMA_PORT}"
    else
      echo "→ 启动 Ollama…"
      nohup ollama serve >"${LOG_DIR}/ollama.log" 2>&1 &
      wait_http "$OLLAMA_PORT" /api/version 15 "Ollama" || true
    fi
  else
    echo "· 未检测到 Ollama：可后续在设置面板填云端 Key，或先用试用模式"
  fi

  # -------------------------------------------------------------------------
  # 2. Sidecar（Python Agent 服务）
  # -------------------------------------------------------------------------

  if port_in_use "$SIDECAR_PORT"; then
    echo "✓ sidecar 已在运行：127.0.0.1:${SIDECAR_PORT}，跳过"
  else
    echo "→ 启动 sidecar…"
    (cd "${ROOT}/server" && nohup uv run uvicorn mochi_server.main:app \
      --port "$SIDECAR_PORT" >"${LOG_DIR}/sidecar.log" 2>&1 &)
    wait_http "$SIDECAR_PORT" /health 30 "sidecar" || exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 3. 前端（Vite dev server）
# ---------------------------------------------------------------------------

if port_in_use "$WEB_PORT"; then
  echo "✓ 前端已在运行：127.0.0.1:${WEB_PORT}，跳过"
else
  echo "→ 启动前端…"
  (cd "$ROOT" && nohup pnpm dev:web >"${LOG_DIR}/web.log" 2>&1 &)
  wait_http "$WEB_PORT" / 30 "前端" || exit 1
fi

cat <<EOF

────────────────────────────────────────────
  Mochi 开发环境已就绪 🍡
  前端:    http://localhost:${WEB_PORT}
  sidecar: http://127.0.0.1:${SIDECAR_PORT}/health
  日志:    ${LOG_DIR}/
  停止:    ./scripts/stop.sh（--all 连同 Ollama）
────────────────────────────────────────────
EOF
