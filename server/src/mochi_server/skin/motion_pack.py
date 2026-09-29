"""动作扩展包导入（G4，动作扩展方案 M-G L3 层）。

给**已导入的用户皮肤**追加原创 motion3.json 动作，免重新打包整个皮肤：
zip 内 ``pack.json``（根或单层子目录，与 skin.json 同惯例）声明目标皮肤、
动作文件与注册表合并项；导入时校验 motion3.json 结构、合并 model3.json
的 ``FileReferences.Motions`` 与 skin.json 的 ``capabilities.motionGroups``
+ ``actions``，合并前备份原文件（可回滚）。

红线：
- **仅用户皮肤可追加**（内置皮肤经前端资产链路分发，不可写）；
- 组名 / 动作 id 冲突一律 409 拒绝（不静默覆盖）；
- motion3.json 须为原创资产，pack.json ``license`` 必填（授权红线，
  复用 LICENSE-Live2D.md 登记）；
- zip-slip / 大小 / 条目数防护与皮肤包导入同一套（importer.py）。

所有失败抛 HTTPException(422/409)，detail 为可读文案供前端直接展示。
"""

from __future__ import annotations

import io
import json
import logging
import zipfile

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator

from ..paths import get_skins_dir
from ..skin_manifest import SkinAction, SkinManifest
from .importer import MAX_ZIP_ENTRIES, MAX_ZIP_SIZE, _assert_safe_paths
from .registry import SkinRegistry

logger = logging.getLogger(__name__)

#: motion 组名：字母开头，可含数字/下标 @（Cubism 惯例如 Tap@Body）
_MOTION_GROUP_PATTERN = r"^[A-Za-z][A-Za-z0-9_@]{0,63}$"
_MOTION_FILE_SUFFIX = ".motion3.json"

# motion3.json 曲线段类型标记（Cubism 3 规范）：linear/bezier/stepped/贝塞尔分段
_SEGMENT_TYPES = frozenset({0, 1, 2, 3})
# 各类型标记之后的坐标数（linear/stepped 1 点、bezier 3 点、type3 至少 1 点）
_MIN_POINTS_AFTER_MARK = {0: 2, 1: 6, 2: 2, 3: 2}
# 末点时间 vs Meta.Duration 的数值容差
_DURATION_EPSILON = 1e-3


class MotionPackEntry(BaseModel):
    """单条动作：组名 + 包内文件（相对 pack.json 所在目录）。"""

    group: str = Field(..., pattern=_MOTION_GROUP_PATTERN)
    file: str

    model_config = {"populate_by_name": True}


class MotionPackManifest(BaseModel):
    """pack.json：动作扩展包清单（G4）。"""

    target_skin: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,31}$", alias="targetSkin")
    name: str = ""
    license: str = Field(..., min_length=1)
    motions: list[MotionPackEntry] = Field(..., min_length=1)
    actions: list[SkinAction] = Field(..., min_length=1)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_consistency(self) -> MotionPackManifest:
        """交叉校验：动作实现引用的组必须都在包内声明。"""
        groups = {m.group for m in self.motions}
        files = [m.file for m in self.motions]
        duplicates = sorted({f for f in files if files.count(f) > 1})
        if duplicates:
            raise ValueError(f"动作文件重复声明：{', '.join(duplicates)}")
        for action in self.actions:
            declared = set(action.live2d.motion_groups)
            if action.live2d.param_envelope is not None and not declared:
                continue  # 包络-only 动作合法（不引用 motion 组）
            unknown = declared - groups
            if unknown:
                raise ValueError(
                    f"动作 {action.id} 引用了包内未声明的动作组：{', '.join(sorted(unknown))}"
                )
        return self


def validate_motion3_json(raw: object, filename: str) -> float:
    """motion3.json 结构校验（Cubism 3）；合法返回 Meta.Duration（秒）。

    与 scripts/validate-motion3.mjs 同一逻辑（脚本用于资产仓库 CI，
    此处用于导入时兜底——两端口径一致）。
    """
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail=f"{filename}：不是 JSON 对象")
    version = raw.get("Version")
    if version != 3:
        raise HTTPException(
            status_code=422, detail=f"{filename}：Version 必须为 3（收到 {version!r}）"
        )
    meta = raw.get("Meta")
    if not isinstance(meta, dict):
        raise HTTPException(status_code=422, detail=f"{filename}：缺少 Meta 对象")
    duration = meta.get("Duration")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        raise HTTPException(status_code=422, detail=f"{filename}：Meta.Duration 必须为正数")
    curves = raw.get("Curves")
    if not isinstance(curves, list) or not curves:
        raise HTTPException(status_code=422, detail=f"{filename}：Curves 须为非空数组")
    for curve in curves:
        _validate_curve(curve, filename, duration)
    return float(duration)


def _validate_curve(curve: object, filename: str, duration: float) -> None:
    if not isinstance(curve, dict):
        raise HTTPException(status_code=422, detail=f"{filename}：Curves 元素须为对象")
    target = curve.get("Target")
    if target != "Parameter":
        raise HTTPException(
            status_code=422,
            detail=f'{filename}：Curves[].Target 必须为 "Parameter"（收到 {target!r}）',
        )
    param_id = curve.get("Id")
    if not isinstance(param_id, str) or not param_id:
        raise HTTPException(status_code=422, detail=f"{filename}：Curves[].Id 须为非空参数 id")
    segments = curve.get("Segments")
    if not isinstance(segments, list) or len(segments) < 4:
        raise HTTPException(
            status_code=422, detail=f"{filename}：参数 {param_id} 的 Segments 须为 ≥4 个数字"
        )
    for value in segments:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise HTTPException(
                status_code=422, detail=f"{filename}：参数 {param_id} 的 Segments 含非数字"
            )
    # 首点为段起点
    pos = 2
    last_t = float(segments[0])
    while pos < len(segments):
        mark = segments[pos]
        if mark not in _SEGMENT_TYPES or not isinstance(mark, int):
            raise HTTPException(
                status_code=422,
                detail=f"{filename}：参数 {param_id} 的段类型标记非法：{mark!r}（合法 0/1/2/3）",
            )
        need = _MIN_POINTS_AFTER_MARK[int(mark)]
        if pos + 1 + need > len(segments):
            raise HTTPException(
                status_code=422, detail=f"{filename}：参数 {param_id} 的段数据不完整（标记 {mark}）"
            )
        last_t = float(segments[pos + need - 1])  # 段末点时间（消耗数据的倒数第二位）
        pos += 1 + need
    if last_t > duration + _DURATION_EPSILON:
        raise HTTPException(
            status_code=422,
            detail=f"{filename}：参数 {param_id} 曲线末点 {last_t}s 超出 Meta.Duration {duration}s",
        )


def _load_pack(zf: zipfile.ZipFile) -> tuple[MotionPackManifest, str]:
    """解析 pack.json（根或单层子目录内），返回（清单, 目录前缀）。"""
    names = zf.namelist()
    entry = next(
        (n for n in names if (n == "pack.json" or n.endswith("/pack.json")) and n.count("/") <= 1),
        None,
    )
    if entry is None:
        raise HTTPException(status_code=422, detail="zip 内缺少 pack.json（须位于根或单层目录内）")
    try:
        raw = json.loads(zf.read(entry))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"pack.json 校验失败：{exc}") from exc
    try:
        pack = MotionPackManifest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"pack.json 校验失败：{exc}") from exc
    prefix = entry.rsplit("/", 1)[0] if "/" in entry else ""
    return pack, prefix


def _validate_pack_files(zf: zipfile.ZipFile, pack: MotionPackManifest, prefix: str) -> None:
    """包内文件校验：声明的 motion 文件都存在且结构合法；越权路径拒绝。"""
    names = set(zf.namelist())

    def _resolve(rel: str) -> str:
        return f"{prefix}/{rel}" if prefix else rel

    for entry in pack.motions:
        if entry.file.startswith("/") or ".." in entry.file.split("/"):
            raise HTTPException(status_code=422, detail=f"非法动作文件路径：{entry.file}")
        if not entry.file.endswith(_MOTION_FILE_SUFFIX):
            raise HTTPException(
                status_code=422, detail=f"动作文件须以 {_MOTION_FILE_SUFFIX} 结尾：{entry.file}"
            )
        resolved = _resolve(entry.file)
        if resolved not in names:
            raise HTTPException(status_code=422, detail=f"zip 内缺少动作文件：{entry.file}")
        try:
            raw = json.loads(zf.read(resolved))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422, detail=f"{entry.file} 不是有效 JSON：{exc}"
            ) from exc
        validate_motion3_json(raw, entry.file)


def import_motion_pack(content: bytes, registry: SkinRegistry) -> SkinManifest:
    """动作扩展包导入（G4）：校验 → 备份 → 合并 model3.json 与 skin.json → 登记。"""
    if len(content) > MAX_ZIP_SIZE:
        raise HTTPException(
            status_code=422, detail=f"文件过大（zip 上限 {MAX_ZIP_SIZE // 1024 // 1024}MB）"
        )
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="不是有效的 zip 文件") from None
    if len(zf.namelist()) > MAX_ZIP_ENTRIES:
        raise HTTPException(status_code=422, detail=f"zip 条目过多（上限 {MAX_ZIP_ENTRIES}）")
    pack, prefix = _load_pack(zf)
    _validate_pack_files(zf, pack, prefix)

    target = registry.get(pack.target_skin)
    if target is None:
        raise HTTPException(
            status_code=422,
            detail=f"目标皮肤不存在或不可扩展：{pack.target_skin}（仅用户导入的皮肤可追加动作）",
        )

    skin_dir = get_skins_dir() / pack.target_skin
    if not skin_dir.is_dir():
        raise HTTPException(
            status_code=422,
            detail=f"目标皮肤目录不存在：{pack.target_skin}（仅用户导入的皮肤可追加动作）",
        )
    _assert_safe_paths(zf, skin_dir)

    # -- 合并前冲突检查（全部通过才动手，失败不残留半合并状态）--
    model3_path = skin_dir / target.model_file
    if not model3_path.is_file():
        raise HTTPException(status_code=422, detail=f"目标皮肤缺少模型文件：{target.model_file}")
    model3 = json.loads(model3_path.read_text(encoding="utf-8"))
    file_refs = model3.setdefault("FileReferences", {})
    if not isinstance(file_refs, dict):
        file_refs = {}
        model3["FileReferences"] = file_refs
    motions_table = file_refs.setdefault("Motions", {})
    if not isinstance(motions_table, dict):
        motions_table = {}
        file_refs["Motions"] = motions_table
    clashes = [e.group for e in pack.motions if e.group in motions_table]
    if clashes:
        raise HTTPException(
            status_code=409,
            detail=f"动作组名已存在（不覆盖）：{', '.join(sorted(clashes))}",
        )
    existing_ids = {a.id for a in target.actions}
    id_clashes = sorted(a.id for a in pack.actions if a.id in existing_ids)
    if id_clashes:
        raise HTTPException(
            status_code=409, detail=f"动作 id 已存在（不覆盖）：{', '.join(id_clashes)}"
        )

    # -- 备份（仅首次，保留原始状态；重复导入扩展包不覆盖首次备份）--
    _backup_once(model3_path, model3_path.with_suffix(".orig.json"))
    skin_json_path = skin_dir / "skin.json"
    if skin_json_path.is_file():
        _backup_once(skin_json_path, skin_json_path.with_suffix(".orig.json"))

    # -- 合并 model3.json：新组各挂一条 {File: ...}（解包后的相对路径）--
    for entry in pack.motions:
        motions_table[entry.group] = [{"File": entry.file}]
    model3_path.write_text(json.dumps(model3, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- 解包动作文件（仅声明的 motions/ 文件）--
    for entry in pack.motions:
        resolved = f"{prefix}/{entry.file}" if prefix else entry.file
        dest = skin_dir / entry.file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(resolved))

    # -- 合并 skin.json：capabilities.motionGroups 追加 + actions 合并 + 授权登记--
    new_groups = [e.group for e in pack.motions]
    manifest = target.model_copy(
        update={
            "capabilities": target.capabilities.model_copy(
                update={"motion_groups": [*target.capabilities.motion_groups, *new_groups]}
            ),
            "actions": [*target.actions, *pack.actions],
            "credits": {
                **target.credits,
                _pack_credit_key(pack.name, target.credits): pack.license,
            },
        }
    )
    skin_json_path.write_text(
        json.dumps(
            manifest.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    registry.add_user_skin(manifest)
    logger.info(
        "动作扩展包导入：%s → %s（+%d 组 / +%d 动作，license=%s）",
        pack.name or "(未命名)",
        pack.target_skin,
        len(new_groups),
        len(pack.actions),
        pack.license,
    )
    return manifest


def _backup_once(src_path, backup_path) -> None:
    if not backup_path.exists():
        backup_path.write_bytes(src_path.read_bytes())


def _pack_credit_key(pack_name: str, credits: dict[str, str]) -> str:
    base = f"motionPack:{pack_name}" if pack_name else "motionPack"
    if base not in credits:
        return base
    n = 2
    while f"{base}#{n}" in credits:
        n += 1
    return f"{base}#{n}"
