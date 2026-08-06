"""内置静态皮肤生成（M1-S1，dev-only，ADR-0006 D4）。

把 docs/images/ 下用户授权的白底 PNG 抠成透明底 avatar.png，落入
assets/skins/<id>/（skin.json 手工维护在仓库内，本脚本只生成图片，幂等）。

白底去除策略：从图像边界的「近白」像素做连通域 flood-fill（BFS）——
只去除与边界连通的背景，角色内部的白色（衬衫等）不受影响；
alpha 蒙版做一次高斯模糊给边缘羽化，避免生硬锯齿。

运行：uv run --project server python scripts/make_static_skins.py
（Pillow 在 server dev 依赖组，不进生产包）。
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parents[1]

# 源图 → 皮肤 id（julia 过大降采样到 ≤1024，控包体）
SOURCES = {
    "mochi-julia": ("docs/images/julia.png", 1024),
    "mochi-snj": ("docs/images/snj1.png", None),
}

WHITE_THRESHOLD = 235  # min(r,g,b) ≥ 该值视为近白
MAX_DIMENSION = 1024


def _downscale(img: Image.Image, limit: int | None) -> Image.Image:
    cap = limit or MAX_DIMENSION
    w, h = img.size
    if max(w, h) <= cap:
        return img
    scale = cap / max(w, h)
    return img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)


def _remove_white_background(img: Image.Image) -> Image.Image:
    """边界连通近白域 → 透明；边缘高斯羽化。"""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    pixels = rgba.load()

    def is_white(x: int, y: int) -> bool:
        r, g, b, _a = pixels[x, y]
        return min(r, g, b) >= WHITE_THRESHOLD

    background = bytearray(w * h)  # 1 = 背景
    queue: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if is_white(x, y) and not background[y * w + x]:
                background[y * w + x] = 1
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if is_white(x, y) and not background[y * w + x]:
                background[y * w + x] = 1
                queue.append((x, y))

    while queue:
        cx, cy = queue.popleft()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                idx = ny * w + nx
                if not background[idx] and is_white(nx, ny):
                    background[idx] = 1
                    queue.append((nx, ny))

    alpha = bytes(0 if background[i] else 255 for i in range(w * h))
    mask = Image.frombytes("L", (w, h), alpha).filter(ImageFilter.GaussianBlur(0.8))
    rgba.putalpha(mask)
    return rgba


def main() -> int:
    for skin_id, (source, limit) in SOURCES.items():
        src = REPO_ROOT / source
        if not src.is_file():
            print(f"[skip] 源图缺失：{src}", file=sys.stderr)
            return 1
        out_dir = REPO_ROOT / "assets" / "skins" / skin_id
        out_dir.mkdir(parents=True, exist_ok=True)

        img = _downscale(Image.open(src), limit)
        result = _remove_white_background(img)
        out = out_dir / "avatar.png"
        result.save(out, optimize=True)
        print(f"[ok] {skin_id}: {result.size[0]}x{result.size[1]} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
