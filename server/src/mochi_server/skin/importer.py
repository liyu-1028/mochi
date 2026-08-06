"""皮肤导入（M1-S1，功能清单 3.4 图片即皮肤 / 3.5 导入校验）。

两种入口按 magic bytes 分流：
- PNG：校验头与 IHDR 尺寸 → 落盘 avatar.png + 生成静态清单（零图像依赖，
  运行时不引 Pillow，ADR-0006 D5）；
- zip 皮肤包：根或单层子目录内须有 skin.json，清单与资源文件校验通过后
  解包；**逐成员校验解包路径落在皮肤目录内（zip-slip 防护）**。

所有失败抛 HTTPException(422/409)，detail 为可读文案供前端直接展示。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import zipfile

from fastapi import HTTPException
from pydantic import ValidationError

from ..paths import get_skins_dir
from ..skin_manifest import SkinManifest, default_static_animation, default_static_emotion_mapping

MAX_PNG_SIZE = 10 * 1024 * 1024  # 10MB
MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50MB（Live2D 包含 2048 贴图）
MAX_ZIP_ENTRIES = 500
MAX_IMAGE_DIMENSION = 4096
MIN_IMAGE_DIMENSION = 64

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ZIP_MAGIC = b"PK\x03\x04"


def _validate_png(content: bytes) -> tuple[int, int]:
    """校验 PNG magic 与 IHDR 宽高（规范固定位置，big-endian uint32）。"""
    if len(content) < 24:
        raise HTTPException(status_code=422, detail="PNG 文件损坏（数据不完整）")
    if content[:8] != PNG_MAGIC:
        raise HTTPException(status_code=422, detail="不是有效的 PNG 文件")
    width = int.from_bytes(content[16:20], "big")
    height = int.from_bytes(content[20:24], "big")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise HTTPException(
            status_code=422,
            detail=f"图片尺寸过大（上限 {MAX_IMAGE_DIMENSION}×{MAX_IMAGE_DIMENSION}）",
        )
    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        raise HTTPException(
            status_code=422,
            detail=f"图片尺寸过小（下限 {MIN_IMAGE_DIMENSION}×{MIN_IMAGE_DIMENSION}）",
        )
    return width, height


def _reserve_skin_dir(skin_id: str, registry) -> None:
    if not _ID_PATTERN.match(skin_id):
        raise HTTPException(
            status_code=422, detail=f"非法皮肤 ID：{skin_id}（仅限小写字母/数字/连字符）"
        )
    if registry.has(skin_id):
        raise HTTPException(status_code=409, detail=f"皮肤 ID 已存在：{skin_id}")


def import_png_skin(
    content: bytes,
    skin_id: str | None,
    skin_name: str | None,
    registry,
) -> SkinManifest:
    """图片即皮肤（3.4）：PNG → 静态皮肤，立即注册可用。"""
    if len(content) > MAX_PNG_SIZE:
        raise HTTPException(
            status_code=422, detail=f"文件过大（PNG 上限 {MAX_PNG_SIZE // 1024 // 1024}MB）"
        )
    _validate_png(content)

    if not skin_id:
        skin_id = f"png-{hashlib.sha256(content).hexdigest()[:12]}"
    _reserve_skin_dir(skin_id, registry)

    skin_dir = get_skins_dir() / skin_id
    skin_dir.mkdir(parents=True, exist_ok=True)
    (skin_dir / "avatar.png").write_bytes(content)

    manifest = SkinManifest(
        id=skin_id,
        name=skin_name or skin_id,
        resourceType="static",
        license="User uploaded",
        imageFile="avatar.png",
        animation=default_static_animation(),
        emotionMapping=default_static_emotion_mapping(),
    )
    (skin_dir / "skin.json").write_text(
        json.dumps(
            manifest.model_dump(by_alias=True, exclude_none=True), indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    registry.add_user_skin(manifest)
    return manifest


def _assert_safe_paths(zf: zipfile.ZipFile, target_dir) -> None:
    """zip-slip 防护：任何成员解出 target_dir 之外即拒绝（ADR-0006 D8）。

    须在创建目录前调用，失败不残留空皮肤目录。
    """
    base = target_dir.resolve()
    for name in zf.namelist():
        resolved = (base / name).resolve()
        if resolved != base and not resolved.is_relative_to(base):
            raise HTTPException(status_code=422, detail=f"zip 包含越权路径：{name}")


def import_zip_skin(content: bytes, skin_id: str | None, registry) -> SkinManifest:
    """zip 皮肤包导入（3.5）：skin.json 须在根或单层子目录内。"""
    if len(content) > MAX_ZIP_SIZE:
        raise HTTPException(
            status_code=422, detail=f"文件过大（zip 上限 {MAX_ZIP_SIZE // 1024 // 1024}MB）"
        )
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="不是有效的 zip 文件") from None

    names = zf.namelist()
    if len(names) > MAX_ZIP_ENTRIES:
        raise HTTPException(status_code=422, detail=f"zip 条目过多（上限 {MAX_ZIP_ENTRIES}）")
    manifest_entry = next((n for n in names if n.endswith("skin.json") and n.count("/") <= 1), None)
    if manifest_entry is None:
        raise HTTPException(status_code=422, detail="zip 内缺少 skin.json（须位于根或单层目录内）")

    try:
        manifest = SkinManifest.model_validate(json.loads(zf.read(manifest_entry)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"skin.json 校验失败：{exc}") from exc

    target_id = skin_id or manifest.id
    _reserve_skin_dir(target_id, registry)

    prefix = manifest_entry.rsplit("/", 1)[0] if "/" in manifest_entry else ""

    def _resolve(rel: str) -> str:
        return f"{prefix}/{rel}" if prefix else rel

    if (
        manifest.resource_type == "live2d"
        and manifest.model_file
        and (_resolve(manifest.model_file) not in names)
    ):
        raise HTTPException(status_code=422, detail=f"zip 内缺少模型文件：{manifest.model_file}")
    if (
        manifest.resource_type == "static"
        and manifest.image_file
        and (_resolve(manifest.image_file) not in names)
    ):
        raise HTTPException(status_code=422, detail=f"zip 内缺少图片文件：{manifest.image_file}")

    skin_dir = get_skins_dir() / target_id
    _assert_safe_paths(zf, skin_dir)
    skin_dir.mkdir(parents=True, exist_ok=True)
    zf.extractall(skin_dir)
    if prefix:
        # 单层子目录打包：提升到皮肤根目录，保持 <skins>/<id>/skin.json 约定
        nested = skin_dir / prefix
        for child in nested.iterdir():
            shutil.move(str(child), str(skin_dir / child.name))
        shutil.rmtree(nested, ignore_errors=True)

    registry.add_user_skin(manifest)
    return manifest
