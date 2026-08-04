#!/usr/bin/env bash
# Mochi 本机一条龙：打包 → 安装 → 启动（macOS）。
#
# 用法：
#   ./scripts/build-install-run.sh             # 构建 dmg → 安装到 /Applications → 启动
#   ./scripts/build-install-run.sh --app       # 跳过 dmg，直接用 .app 产物安装（更快）
#   ./scripts/build-install-run.sh --no-launch # 只打包安装，不自动启动
#
# 与 CI 的关系：release.yml 负责跨平台出包（v* tag），本脚本只服务本机
# 快速验证「真实安装版」——release sidecar、监督重启、冷启动都与用户拿到的一致。
# Windows 打包走 CI 矩阵，本脚本不支持。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# uv / cargo 默认安装位置可能不在 PATH
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

SIDECAR_PORT=8199
INSTALL_DIR="/Applications"
APP_NAME="Mochi.app"
BUNDLE_DIR="$ROOT/apps/desktop/src-tauri/target/release/bundle"

VERSION="$(grep -o '"version": *"[^"]*"' "$ROOT/apps/desktop/src-tauri/tauri.conf.json" | head -1 | cut -d'"' -f4)"

# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------

APP_ONLY=false
LAUNCH=true
for arg in "$@"; do
  case "$arg" in
    --app) APP_ONLY=true ;;
    --no-launch) LAUNCH=false ;;
    -h | --help)
      grep '^#' "$0" | head -9 | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "✗ 未知参数：${arg}（--help 查看用法）" >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# 工具函数与前置检查
# ---------------------------------------------------------------------------

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

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
  echo "  ✗ ${name} 启动超时（日志在应用内，见 Console 或后续落盘方案）"
  return 1
}

if [ "$(uname -s)" != "Darwin" ]; then
  echo "✗ 本脚本仅支持 macOS（Windows 打包走 CI：.github/workflows/release.yml）" >&2
  exit 1
fi

for tool in pnpm node uv cargo hdiutil ditto; do
  if ! command_exists "$tool"; then
    echo "✗ 缺少依赖：${tool}（安装指引见 README「开发环境准备」）" >&2
    exit 1
  fi
done

if [ ! -d "$ROOT/node_modules" ]; then
  echo "→ 首次运行，安装 JS 依赖…"
  (cd "$ROOT" && pnpm install)
fi

# ---------------------------------------------------------------------------
# 第 1 步：停掉正在运行的 Mochi（安装版 + 开发版），等 sidecar 释放端口
# ---------------------------------------------------------------------------

stop_running_instances() {
  local killed=false
  # SIGTERM：桌面壳退出；sidecar 由父进程看门狗 2s 内自退（entry.py）
  for pattern in "${INSTALL_DIR}/${APP_NAME}" "target/debug/mochi-desktop"; do
    if pkill -f "$pattern" 2>/dev/null; then
      killed=true
    fi
  done
  if [ "$killed" = true ]; then
    echo "→ 已停止运行中的 Mochi，等待 sidecar 释放端口 ${SIDECAR_PORT}…"
    for _ in $(seq 1 10); do
      port_in_use "$SIDECAR_PORT" || break
      sleep 1
    done
    if port_in_use "$SIDECAR_PORT"; then
      echo "  ! 端口 ${SIDECAR_PORT} 仍被占用：新实例的监督线程会退避重试，通常可自愈"
    fi
  fi
}

stop_running_instances

# ---------------------------------------------------------------------------
# 第 2 步：打包（beforeBuildCommand 自动串起 Core 下载 → sidecar → 前端构建）
# ---------------------------------------------------------------------------

if [ "$APP_ONLY" = true ]; then
  BUNDLES="app"
  echo "→ 打包（.app 快速模式，跳过 dmg 制作）…"
else
  BUNDLES="dmg"
  echo "→ 打包 dmg（首次 release 构建较慢，之后增量会快）…"
fi

run_tauri_build() {
  (cd "$ROOT" && pnpm --filter @mochi/desktop exec tauri build --bundles "$BUNDLES")
}

if ! run_tauri_build; then
  # bundle_dmg.sh 偶发被 Finder 竞态击败（hdiutil/AppleScript 时序），残留
  # 挂载的临时 rw 镜像会让后续构建继续失败——清理残留后重试一次
  # （cargo release 产物已生成，重试成本只剩 dmg 制作）
  echo "  ! 打包失败，清理 bundle_dmg 残留挂载后重试…"
  hdiutil info | grep 'image-path.*bundle/macos/rw\.' | awk -F': ' '{print $2}' | while read -r img; do
    hdiutil detach "$img" -force -quiet 2>/dev/null || true
  done
  rm -f "$BUNDLE_DIR"/macos/rw.*.dmg
  run_tauri_build
fi

# ---------------------------------------------------------------------------
# 第 3 步：安装到 /Applications
# ---------------------------------------------------------------------------

MOUNT_POINT=""
# 卸载 dmg：刚 ditto 完的卷可能被 Spotlight 索引短暂占用，重试数次再 -force；
# 仍失败则提示手动弹出（绝不静默吞掉，避免 /Volumes 残留挂载）。
unmount_dmg() {
  if [ -z "$MOUNT_POINT" ]; then
    return 0
  fi
  for _ in 1 2 3 4 5; do
    if hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null; then
      MOUNT_POINT=""
      return 0
    fi
    sleep 1
  done
  if hdiutil detach "$MOUNT_POINT" -force -quiet 2>/dev/null; then
    MOUNT_POINT=""
    return 0
  fi
  echo "  ! 未能自动卸载 dmg，请手动弹出：hdiutil detach \"$MOUNT_POINT\"" >&2
  return 1
}
cleanup() {
  unmount_dmg || true # EXIT 兜底：任何提前退出路径也不留挂载
}
trap cleanup EXIT

if [ "$APP_ONLY" = true ]; then
  APP_SRC="$(ls -d "$BUNDLE_DIR"/macos/*.app 2>/dev/null | head -1)"
else
  DMG="$(ls -t "$BUNDLE_DIR"/dmg/*.dmg 2>/dev/null | head -1)"
  if [ -z "$DMG" ]; then
    echo "✗ 未找到 dmg 产物：${BUNDLE_DIR}/dmg/" >&2
    exit 1
  fi
  echo "→ 挂载 $(basename "$DMG")（$(du -h "$DMG" | cut -f1)）…"
  MOUNT_POINT="$(hdiutil attach "$DMG" -nobrowse -noautoopen | grep -o '/Volumes/.*' | head -1)"
  if [ -z "$MOUNT_POINT" ]; then
    echo "✗ dmg 挂载失败" >&2
    exit 1
  fi
  APP_SRC="$(ls -d "$MOUNT_POINT"/*.app 2>/dev/null | head -1)"
fi

if [ -z "${APP_SRC:-}" ] || [ ! -d "$APP_SRC" ]; then
  echo "✗ 未找到 .app 产物：${APP_SRC:-<空>}" >&2
  exit 1
fi

echo "→ 安装到 ${INSTALL_DIR}/${APP_NAME}（覆盖旧版本）…"
rm -rf "${INSTALL_DIR}/${APP_NAME}"
ditto "$APP_SRC" "${INSTALL_DIR}/${APP_NAME}"
unmount_dmg || true

# ---------------------------------------------------------------------------
# 第 4 步：启动
# ---------------------------------------------------------------------------

if [ "$LAUNCH" = false ]; then
  cat <<EOF

────────────────────────────────────────────
  Mochi v${VERSION} 已安装 🍡（未启动）
  位置: ${INSTALL_DIR}/${APP_NAME}
  启动: open ${INSTALL_DIR}/${APP_NAME}
────────────────────────────────────────────
EOF
  exit 0
fi

echo "→ 启动 ${APP_NAME}…"
open "${INSTALL_DIR}/${APP_NAME}"
# 安装版 sidecar 由桌面壳 spawn（release 分支）；/health 就绪即整链路可用
wait_http "$SIDECAR_PORT" /health 15 "sidecar（安装版）" || true

cat <<EOF

────────────────────────────────────────────
  Mochi v${VERSION} 打包安装完成，窗口应已出现 🍡
  位置:  ${INSTALL_DIR}/${APP_NAME}
  退出:  直接关闭窗口（sidecar 自动回收）
────────────────────────────────────────────
EOF
