#!/usr/bin/env bash
# 构建 sidecar 生产产物（PyInstaller onedir）并落位 Tauri bundle.resources。
#
# 用法：
#   ./scripts/package-sidecar.sh   # tauri build 前自动调用（beforeBuildCommand）
#
# 产物：apps/desktop/src-tauri/binaries/sidecar/（整个 onedir 目录）
# tauri.conf.json 的 bundle.resources 把该目录打进安装包：
#   macOS → Mochi.app/Contents/Resources/sidecar/
#   Windows → <安装目录>/resources/sidecar/
# Rust 侧经 app.path().resource_dir() 定位并 spawn（sidecar.rs release 分支）。
#
# 选型（onedir 而非 onefile/externalBin）与实测数据：
# docs/internal/adr/0004-packaging.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "✗ 缺少依赖：uv（安装指引见 README「开发环境准备」）" >&2
  exit 1
fi

echo "→ 构建 sidecar 生产产物（PyInstaller onedir）"
(cd "$ROOT/server" && uv run pyinstaller --clean --noconfirm packaging/mochi-server.spec)

SRC="$ROOT/server/dist/mochi-server"
if [ ! -d "$SRC" ]; then
  echo "✗ PyInstaller 产物缺失：server/dist/mochi-server/" >&2
  exit 1
fi

DEST="$ROOT/apps/desktop/src-tauri/binaries/sidecar"
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -R "$SRC" "$DEST"
chmod +x "$DEST/mochi-server" 2>/dev/null || true        # macOS/Linux 可执行位
chmod +x "$DEST/mochi-server.exe" 2>/dev/null || true     # Windows

SIZE="$(du -sh "$DEST" | cut -f1)"
echo "✓ sidecar 已落位：apps/desktop/src-tauri/binaries/sidecar/（${SIZE}）"
