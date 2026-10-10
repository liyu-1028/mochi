"""Original VRMA files: role defaults plus user imports and metadata overrides."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from ..events import ACTION_LABELS
from ..paths import get_motion_library_dir

logger = logging.getLogger(__name__)

#: 用户下载的 VRM Animation 文件
MOTION_FILE_EXTENSIONS = frozenset({".vrma"})
#: 单文件大小上限（字节）：3D 动画文件常见 1–20MB，50MB 防异常投递
MOTION_FILE_MAX_BYTES = 50 * 1024 * 1024
#: 官方词表风格 id（snake_case）
WORD_ID_PATTERN = r"^[a-z][a-z0-9_]{0,47}$"
#: 社区扩展命名空间 id
EXT_ID_PATTERN = r"^ext\.[a-z0-9-]{2,16}\.[a-z][a-z0-9_]{0,47}$"
#: 行为池标签（P2.7 首批；P3 扩 reminder 空间行为族）
MOTION_TAGS = frozenset({"idle", "greeting", "reminder"})


class MotionEntry(BaseModel):
    """动作库条目（camelCase 与前端一致）。"""

    id: str
    label: str = Field(..., min_length=1, max_length=48)
    kind: str = Field(default="oneshot", pattern=r"^(oneshot|loop)$")
    duration_ms: int = Field(default=2000, ge=100, le=60_000, alias="durationMs")
    priority: int = Field(default=50, ge=0, le=100)
    cooldown_ms: int = Field(default=0, ge=0, le=600_000, alias="cooldownMs")
    agent_selectable: bool = Field(default=False, alias="agentSelectable")
    tags: list[str] = Field(default_factory=list)
    category: str = Field(default="custom", pattern=r"^(builtin|custom)$")
    source: str = Field(default="user", pattern=r"^(builtin|user)$")
    skin_id: str | None = Field(default=None, alias="skinId")
    credit: str = Field(default="", max_length=300)
    file: str
    created_at: str = Field(default="", alias="createdAt")

    model_config = {"populate_by_name": True}

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if re.fullmatch(WORD_ID_PATTERN, value) or re.fullmatch(EXT_ID_PATTERN, value):
            return value
        raise ValueError(
            f"动作 id 须为 snake_case（官方词表风格）或 ext.<命名空间>.<名称>；收到：{value}"
        )

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: list[str]) -> list[str]:
        unknown = [t for t in value if t not in MOTION_TAGS]
        if unknown:
            raise ValueError(f"未知标签：{', '.join(unknown)}（合法：{sorted(MOTION_TAGS)}）")
        return value

    @field_validator("file")
    @classmethod
    def _validate_file(cls, value: str) -> str:
        if (
            "/" in value
            or "\\" in value
            or Path(value).suffix.lower() not in MOTION_FILE_EXTENSIONS
        ):
            raise ValueError("file 须为 motions/ 下的 VRMA 文件名（.vrma）")
        return value


class MotionLibrary:
    """动作库。索引读写即时落盘（条目量小，无缓存必要）。"""

    def __init__(self, defaults_dir: Path | None = None) -> None:
        self._dir = get_motion_library_dir()
        packaged = Path(__file__).parent / "defaults" / "mochi-vrm"
        local = Path(__file__).resolve().parents[4] / "assets/local-motions/mochi-vrm-defaults"
        self._defaults_dir = defaults_dir or Path(
            os.environ.get(
                "MOCHI_BUILTIN_MOTIONS_DIR", str(packaged if packaged.exists() else local)
            )
        )
        self._ensure_layout()
        self._preserve_role_defaults()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_all(self, skin_id: str | None = None) -> list[MotionEntry]:
        entries = self._merged_index().values()
        return sorted(
            (e for e in entries if skin_id is None or e.skin_id is None or e.skin_id == skin_id),
            key=lambda e: (e.created_at, e.id),
        )

    def get(self, motion_id: str) -> MotionEntry | None:
        return self._merged_index().get(motion_id)

    def file_path(self, entry: MotionEntry) -> Path:
        if entry.source == "builtin":
            return self._defaults_dir / "motions" / entry.file
        return self._dir / "motions" / entry.file

    # ------------------------------------------------------------------
    # 变更
    # ------------------------------------------------------------------

    def create(self, entry: MotionEntry, content: bytes) -> MotionEntry:
        index = self._read_index()
        existing = self.get(entry.id)
        if existing is not None:
            purpose = ACTION_LABELS.get(entry.id, "自定义动作")
            raise ConflictError(
                f"{purpose}（{entry.id}）已由列表中的「{existing.label}」使用。"
                + (
                    "请选择其他用途。"
                    if existing.source == "builtin"
                    else "请选择其他用途；如需替换，请先删除原动作再导入。"
                )
            )
        filename = f"{entry.id}{Path(entry.file).suffix.lower()}"
        stored = entry.model_copy(update={"file": filename})
        if not stored.created_at:
            stored = stored.model_copy(
                update={"created_at": datetime.now(UTC).isoformat(timespec="seconds")}
            )
        (self._dir / "motions" / filename).write_bytes(content)
        index[stored.id] = stored
        self._write_index(index)
        logger.info("导入动作：%s（%s，%d 字节）", stored.id, stored.file, len(content))
        return stored

    def update(self, motion_id: str, patch: dict) -> MotionEntry:
        index = self._read_index()
        entry = self.get(motion_id)
        if entry is None:
            raise KeyError(motion_id)
        # id/file 不可改（文件名与 id 绑定；改 id = 删了重导）。
        # 合并后整体重新校验（model_copy(update) 不走 alias，camelCase 键会静默丢失）
        editable = {
            k: v
            for k, v in patch.items()
            if k
            in {
                "label",
                "kind",
                "priority",
                "cooldownMs",
                "agentSelectable",
                "tags",
                "category",
                "credit",
            }
        }
        if entry.source == "builtin":
            editable.pop("category", None)
            editable.pop("credit", None)
        updated = MotionEntry.model_validate({**entry.model_dump(by_alias=True), **editable})
        index[motion_id] = updated
        self._write_index(index)
        return updated

    def delete(self, motion_id: str) -> bool:
        entry = self.get(motion_id)
        if entry is not None and entry.source == "builtin":
            raise ValueError("角色内置动作随应用提供，可调整播放设置，不能删除原始素材。")
        index = self._read_index()
        entry = index.pop(motion_id, None)
        if entry is None:
            return False
        self.file_path(entry).unlink(missing_ok=True)
        self._write_index(index)
        return True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _ensure_layout(self) -> None:
        (self._dir / "motions").mkdir(parents=True, exist_ok=True)
        if not (self._dir / "index.json").exists():
            self._write_index({})

    def _preserve_role_defaults(self) -> None:
        """保留本机角色动作；升级后安装目录不再提供素材时仍可播放。"""
        persistent = self._dir / "role-defaults" / "mochi-vrm"
        if self._defaults_dir == persistent:
            return
        entries = self._read_index(self._defaults_dir / "index.json")
        retained = self._read_index(persistent / "index.json")
        for motion_id, entry in entries.items():
            source = self._defaults_dir / "motions" / entry.file
            if not source.is_file():
                continue
            target = persistent / "motions" / entry.file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            retained[motion_id] = entry
        if retained:
            persistent.mkdir(parents=True, exist_ok=True)
            target = persistent / "index.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {"motions": [e.model_dump(by_alias=True) for e in retained.values()]},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary.replace(target)
            self._defaults_dir = persistent

    def _merged_index(self) -> dict[str, MotionEntry]:
        defaults = self._read_index(self._defaults_dir / "index.json")
        users = self._read_index()
        for motion_id, entry in defaults.items():
            override = users.get(motion_id, entry)
            users[motion_id] = override.model_copy(
                update={
                    "source": "builtin",
                    "category": "builtin",
                    "skin_id": entry.skin_id,
                    "file": entry.file,
                    "credit": entry.credit,
                    "duration_ms": entry.duration_ms,
                }
            )
        return users

    def _read_index(self, path: Path | None = None) -> dict[str, MotionEntry]:
        path = path or self._dir / "index.json"
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {e["id"]: MotionEntry.model_validate(e) for e in raw.get("motions", [])}
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("动作库索引读取失败，按空库处理：%s", exc)
            return {}

    def _write_index(self, index: dict[str, MotionEntry]) -> None:
        payload = {"motions": [e.model_dump(by_alias=True) for e in index.values()]}
        (self._dir / "index.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class ConflictError(Exception):
    """id 冲突（HTTP 409）。"""
