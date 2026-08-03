#!/usr/bin/env bash
# Mochi 本地开发一键启动。
#
# 用法：
#   ./scripts/start.sh            # 默认启动桌面端（Tauri 窗口 + vite + sidecar）
#   ./scripts/start.sh --web-only # 仅启动浏览器可访问的前端 + sidecar（不开窗口）
#
# 桌面端 = `pnpm dev`，由 Tauri 自动拉起 vite（beforeDevCommand）和 sidecar（lib.rs）。
# 日志输出到 logs/（已被 .gitignore 忽略）。停止见 scripts/stop.sh。
# 注意：echo 中变量后紧跟全角字符时必须用 ${VAR} 花括号形式（bash 多字节解析坑）。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

# uv / cargo 默认安装位置可能不在 PATH
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

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

# 兜底清理上一轮可能残留的 Tauri 窗口 / vite（避免 strictPort 启动失败）
prune_stale() {
  pkill -f "target/debug/mochi-desktop" 2>/dev/null || true
  pkill -f "mochi/node_modules/.pnpm/.*vite" 2>/dev/null || true
  # 给端口释放一点时间
  sleep 1
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
# 公共：Ollama（可选）+ Live2D Core 兜底下载
# ---------------------------------------------------------------------------

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

# Live2D Cubism Core：专有代码不入库，幂等下载（校验和一致自动跳过；失败不阻塞）
node "${ROOT}/scripts/download-live2d-core.mjs"

# ---------------------------------------------------------------------------
# 模式 1：默认（桌面端）—— `pnpm dev` 自动管 vite + sidecar
# ---------------------------------------------------------------------------

if [ "$WEB_ONLY" = false ]; then
  prune_stale
  echo "→ 启动桌面端（pnpm dev = Tauri 窗口 + vite + sidecar）…"
  (cd "$ROOT" && nohup pnpm dev >"${LOG_DIR}/tauri-dev.log" 2>&1 &)

  # Tauri dev 会先拉 vite，再启动窗口，sidecar 由 Rust 侧自动 spawn
  wait_http "$WEB_PORT" / 30 "前端（vite，桌面端内部）" || true
  wait_http "$SIDECAR_PORT" /health 30 "sidecar（Tauri 自动拉起）" || true

  cat <<EOF

────────────────────────────────────────────
  Mochi 桌面端已就绪 🍡
  Tauri 窗口会自动弹出；进程在后台，关闭窗口即退出
  vite:   http://localhost:${WEB_PORT}
  sidecar: http://127.0.0.1:${SIDECAR_PORT}/health
  日志:   ${LOG_DIR}/tauri-dev.log
  停止:   ./scripts/stop.sh（--all 连同 Ollama）
────────────────────────────────────────────
EOF
  exit 0
fi

# ---------------------------------------------------------------------------
# 模式 2：--web-only —— 仅启动浏览器侧（无窗口）
# ---------------------------------------------------------------------------

if port_in_use "$SIDECAR_PORT"; then
  echo "✓ sidecar 已在运行：127.0.0.1:${SIDECAR_PORT}，跳过"
else
  echo "→ 启动 sidecar…"
  (cd "${ROOT}/server" && nohup uv run uvicorn mochi_server.main:app \
    --port "$SIDECAR_PORT" >"${LOG_DIR}/sidecar.log" 2>&1 &)
  wait_http "$SIDECAR_PORT" /health 30 "sidecar" || exit 1
fi

if port_in_use "$WEB_PORT"; then
  echo "✓ 前端已在运行：127.0.0.1:${WEB_PORT}，跳过"
else
  echo "→ 启动前端…"
  (cd "$ROOT" && nohup pnpm dev:web >"${LOG_DIR}/web.log" 2>&1 &)
  wait_http "$WEB_PORT" / 30 "前端" || exit 1
fi

cat <<EOF

────────────────────────────────────────────
  Mochi 浏览器开发模式已就绪 🍡
  前端:    http://localhost:${WEB_PORT}
  sidecar: http://127.0.0.1:${SIDECAR_PORT}/health
  日志:    ${LOG_DIR}/
  停止:    ./scripts/stop.sh（--all 连同 Ollama）
────────────────────────────────────────────
EOF