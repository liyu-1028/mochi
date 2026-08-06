"""皮肤注册表（M1-S1，功能清单 3.2/3.3）：内置常量表 + 用户目录扫描。

内置皮肤经前端资产链路分发（base URL 相对 ``/skins/<id>``）；用户皮肤存
``<userData>/skins/<id>/``，经 sidecar 路由分发（绝对 URL，ADR-0006 D2）。
"""

from __future__ import annotations

import json
import logging
import shutil

from pydantic import ValidationError

from ..paths import get_skins_dir
from ..skin_manifest import SkinManifest, SkinSummary, manifest_to_summary
from .builtin import BUILTIN_SKINS

logger = logging.getLogger(__name__)

# 历史配置中 active_skin 的占位值；解析为默认内置皮肤（ADR-0006 D7）。
DEFAULT_SKIN_ID = "hiyori"


def resolve_skin_id(skin_id: str) -> str:
    """``"default"`` → 默认内置皮肤；其余原样返回。集中一处便于后续换默认。"""
    return DEFAULT_SKIN_ID if skin_id == "default" else skin_id


class SkinRegistry:
    """皮肤注册表。用户皮肤在构造时扫描一次，import/delete 后增量维护。"""

    def __init__(self, http_base_url: str = "") -> None:
        # http_base_url 用于拼用户皮肤资源 URL（lifespan 端口确定后注入）。
        self._http_base_url = http_base_url
        self._user_skins: dict[str, SkinManifest] = {}
        self._scan_user_skins()

    def set_base_url(self, url: str) -> None:
        self._http_base_url = url

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_all(self) -> list[SkinSummary]:
        self.reload()  # 读时扫描：手动放置/外部变更即时可见，目录量小成本可忽略
        summaries = [
            manifest_to_summary(m, source="builtin", base_url=f"/skins/{m.id}")
            for m in BUILTIN_SKINS.values()
        ]
        summaries += [
            manifest_to_summary(
                m,
                source="user",
                base_url=f"{self._http_base_url}/user-skins/{m.id}",
            )
            for m in self._user_skins.values()
        ]
        return summaries

    def get(self, skin_id: str) -> SkinManifest | None:
        effective = resolve_skin_id(skin_id)
        if effective in BUILTIN_SKINS:
            return BUILTIN_SKINS[effective]
        self.reload()
        return self._user_skins.get(effective)

    def has(self, skin_id: str) -> bool:
        return self.get(skin_id) is not None

    def is_builtin(self, skin_id: str) -> bool:
        return skin_id in BUILTIN_SKINS

    # ------------------------------------------------------------------
    # 变更
    # ------------------------------------------------------------------

    def add_user_skin(self, manifest: SkinManifest) -> None:
        self._user_skins[manifest.id] = manifest

    def delete(self, skin_id: str) -> bool:
        """删除用户皮肤（内置禁删）；返回目录是否被移除。"""
        if skin_id in BUILTIN_SKINS:
            return False
        self.reload()
        if self._user_skins.pop(skin_id, None) is None:
            return False
        shutil.rmtree(get_skins_dir() / skin_id, ignore_errors=True)
        return True

    def reload(self) -> None:
        self._user_skins.clear()
        self._scan_user_skins()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _scan_user_skins(self) -> None:
        skins_dir = get_skins_dir(create=False)
        if not skins_dir.exists():
            return
        for entry in sorted(skins_dir.iterdir()):
            manifest_path = entry / "skin.json"
            if not entry.is_dir() or not manifest_path.is_file():
                continue
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = SkinManifest.model_validate(raw)
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                logger.warning("用户皮肤 %s 清单校验失败，跳过：%s", entry.name, exc)
                continue
            self._user_skins[manifest.id] = manifest
