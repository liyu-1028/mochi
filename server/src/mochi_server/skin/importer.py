"""角色导入：原始 VRM 文件或 ZIP 皮肤包。

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
import struct
import uuid
import zipfile
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from ..paths import get_skins_dir
from ..skin_manifest import SkinManifest

MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50MB（Live2D 包含 2048 贴图）
MAX_ZIP_ENTRIES = 500

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
ZIP_MAGIC = b"PK\x03\x04"
MAX_VRM_SIZE = 50 * 1024 * 1024


def import_vrm_skin(content: bytes, filename: str, skin_id: str | None, registry) -> SkinManifest:
    """Import a self-contained VRM 0.x/1.0, preserving the model and embedded credits."""
    if len(content) > MAX_VRM_SIZE:
        raise HTTPException(status_code=422, detail="VRM 文件过大（上限 50MB）")
    try:
        if len(content) < 20:
            raise ValueError("文件不完整")
        magic, version, length, json_length, chunk_type = struct.unpack_from("<4sIIII", content)
        if magic != b"glTF" or version != 2 or length != len(content):
            raise ValueError("不是有效的 VRM 二进制文件")
        if chunk_type != 0x4E4F534A or json_length > len(content) - 20:
            raise ValueError("模型 JSON 数据不完整")
        document = json.loads(content[20 : 20 + json_length])
        extensions = document.get("extensions", {})
        vrm = extensions.get("VRMC_vrm") or extensions.get("VRM")
        if not isinstance(vrm, dict):
            raise ValueError("缺少 VRM 角色数据；普通 GLB 和 VRMA 动作不能作为角色导入")
        bones = vrm.get("humanoid", {}).get("humanBones")
        if not isinstance(bones, (dict, list)) or not bones:
            raise ValueError("缺少 VRM 人形骨骼")
        meta = vrm.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError("模型信息格式错误")
        # Downloads and Studio exports embed their textures/buffers. Do not fetch external files.
        for resource in document.get("buffers", []) + document.get("images", []):
            uri = resource.get("uri", "")
            if uri and (not isinstance(uri, str) or not uri.startswith("data:")):
                raise ValueError("模型依赖外部资源，请导出包含贴图的完整 .vrm 文件")
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError, struct.error) as exc:
        raise HTTPException(status_code=422, detail=f"VRM 校验失败：{exc}") from exc

    def text(value) -> str:
        return value.strip() if isinstance(value, str) else ""

    authors = meta.get("authors", [])
    credit = (
        ", ".join(filter(None, (text(author) for author in authors)))
        if isinstance(authors, list)
        else ""
    )
    credit = credit or text(meta.get("author"))
    license_info = text(meta.get("licenseUrl")) or text(meta.get("licenseName"))
    other_license = text(meta.get("otherLicenseUrl"))
    target_id = skin_id or f"vrm-{uuid.uuid4().hex[:12]}"
    _reserve_skin_dir(target_id, registry)
    manifest = SkinManifest(
        id=target_id,
        name=text(meta.get("name")) or text(meta.get("title")) or Path(filename).stem,
        version=text(meta.get("version")) or "1.0.0",
        resourceType="vrm",
        modelFile="model.vrm",
        license=" · ".join(filter(None, (license_info, other_license))),
        credits={"model": credit} if credit else {},
    )
    skin_dir = get_skins_dir() / target_id
    skin_dir.mkdir(parents=True, exist_ok=False)
    try:
        (skin_dir / "model.vrm").write_bytes(content)
        (skin_dir / "skin.json").write_text(
            json.dumps(manifest.model_dump(by_alias=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        shutil.rmtree(skin_dir, ignore_errors=True)
        raise
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
