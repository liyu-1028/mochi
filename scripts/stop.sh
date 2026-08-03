#!/usr/bin/env bash
# Mochi 本地开发一键停止。
#
# 用法：
#   ./scripts/stop.sh        # 停止 sidecar（8199）与前端（1420）
#   ./scripts/stop.sh --all  # 连同 Ollama 一起停止
#
# 注意：echo 中变量后紧跟全角字符时必须用 ${VAR} 花括号形式（bash 多字节解析坑）。
set -uo pipefail

SIDECAR_PORT=8199
WEB_PORT=1420

stop_port() { # stop_port <port> <名称>
  local port=$1 name=$2
  local pids
  pids="$(lsof -ti :"${port}" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill 2>/dev/null
    sleep 1
    # 仍未退出则强杀
    pids="$(lsof -ti :"${port}" 2>/dev/null || true)"
    [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null
    echo "✓ ${name} 已停止（端口 ${port}）"
  else
    echo "· ${name} 未在运行（端口 ${port}）"
  fi
}

# 兜底：清理可能残留的进程树（pnpm/uv 包装进程）
pkill -f "uvicorn mochi_server.main:app" 2>/dev/null
pkill -f "mochi/node_modules/.pnpm/.*vite" 2>/dev/null

stop_port "$WEB_PORT" "前端"
stop_port "$SIDECAR_PORT" "sidecar"

if [ "${1:-}" = "--all" ]; then
  pkill -f "Ollama.app" 2>/dev/null
  pkill -f "ollama serve" 2>/dev/null
  pkill -x ollama 2>/dev/null
  sleep 1
  if curl -s -o /dev/null --max-time 2 http://127.0.0.1:11434/api/version; then
    echo "✗ Ollama 仍在运行（如由 Ollama.app 托管，请从菜单栏退出）"
  else
    echo "✓ Ollama 已停止"
  fi
else
  echo "· 保留 Ollama（如需停止：./scripts/stop.sh --all）"
fi
