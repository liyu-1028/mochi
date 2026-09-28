"""皮肤导入（M1-S1，3.5 zip 皮肤包导入校验）。

zip 皮肤包：根或单层子目录内须有 skin.json，清单与资源文件校验通过后解包；
**逐成员校验解包路径落在皮肤目录内（zip-slip 防护）**。
PNG 图片导入（原 3.4「图片即皮肤」）随静态皮肤类型一并下线（2026-09-28
产品决策：只保留 Live2D 及未来扩展的动态类型）。

所有失败抛 HTTPException(422/409)，detail 为可读文案供前端直接展示。
"""

from __future__ import annotations

import io
import json
import re
import shutil
import zipfile

from fastapi import HTTPException
from pydantic import ValidationError

from ..paths import get_skins_dir
from ..skin_manifest import SkinManifest

MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50MB（Live2D 包含 2048 贴图）
MAX_ZIP_ENTRIES = 500

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
ZIP_MAGIC = b"PK\x03\x04"


def _assert_safe_paths(zf: zipfile.ZipFile, target_dir) -> None:
    """zip-slip 防护：任何成员解出 target_dir 之外即拒绝（ADR-0006 D8）。

    须在创建目录前调用，失败不残留空皮肤目录。
    """
    base = target_dir.resolve()
    for name in zf.namelist():
        resolved = (base / name).resolve()
        if resolved != base and not resolved.is_relative_to(base):
            raise HTTPException(status_code=422, detail=f"zip 包含越权路径：{name}")


def _reserve_skin_dir(skin_id: str, registry) -> None:
    if not _ID_PATTERN.match(skin_id):
        raise HTTPException(
            status_code=422, detail=f"非法皮肤 ID：{skin_id}（仅限小写字母/数字/连字符）"
        )
    if registry.has(skin_id):
        raise HTTPException(status_code=409, detail=f"皮肤 ID 已存在：{skin_id}")


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
        raw = json.loads(zf.read(manifest_entry))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"skin.json 校验失败：{exc}") from exc
    if isinstance(raw, dict) and raw.get("resourceType") == "static":
        raise HTTPException(
            status_code=422, detail="静态皮肤类型已下线（仅支持 live2d 及未来动态类型）"
        )
    try:
        manifest = SkinManifest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"skin.json 校验失败：{exc}") from exc

    target_id = skin_id or manifest.id
    _reserve_skin_dir(target_id, registry)
    original_id = manifest.id
    if target_id != original_id:
        # skin_id 表单覆盖：清单 id 与目录名保持一致（注册表按 manifest.id 登记）
        manifest = manifest.model_copy(update={"id": target_id})

    prefix = manifest_entry.rsplit("/", 1)[0] if "/" in manifest_entry else ""

    def _resolve(rel: str) -> str:
        return f"{prefix}/{rel}" if prefix else rel

    if _resolve(manifest.model_file) not in names:
        raise HTTPException(status_code=422, detail=f"zip 内缺少模型文件：{manifest.model_file}")

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

    if target_id != original_id:
        # zip 内 skin.json 携带原始 id：解包后覆写为与目录名一致的副本
        (skin_dir / "skin.json").write_text(
            json.dumps(
                manifest.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )

    registry.add_user_skin(manifest)
    return manifest
