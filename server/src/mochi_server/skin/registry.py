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

logger = logging.getLogger(__name__)

# 历史兼容说明：配置里可能残留 active_skin="default"（旧内置静态皮肤占位）；
# 静态类型已下线，该值解析不到任何皮肤（get 返回 None → 前端走未设置路径）。

# 内置 VRM 角色（ADR-0011 D6 修订）：模型经 scripts/download-vrm-assets.mjs
# 按固定来源下载至前端资产链 assets/skins/<id>/（gitignore，不入库），
# 前端以相对 base URL ``/skins/<id>`` 取资源（vite dev 中间件 / 打包拷贝）。
# 许可登记：LICENSE-Live2D.md §2。
BUILTIN_SKINS: list[SkinManifest] = [
    SkinManifest(
        id="mochi-vrm",
        name="Mochi",
        version="1.0.0",
        resourceType="vrm",
        license="VRM Public License 1.0 (see model metadata)",
        modelFile="model.vrm",
        credits={"model": "pixiv Inc. (VRM1_Constraint_Twist_Sample)"},
    ),
]
_BUILTIN_BY_ID = {m.id: m for m in BUILTIN_SKINS}


class SkinRegistry:
    """皮肤注册表。用户皮肤在构造时扫描一次，import/delete 后增量维护。"""

    def __init__(self, http_base_url: str = "") -> None:
        # http_base_url 用于拼用户皮肤资源 URL（lifespan 端口确定后注入）。
        self._http_base_url = http_base_url
        self._user_skins: dict[str, SkinManifest] = {}
        self._scan_user_skins()

    def set_base_url(self, url: str) -> None:
        self._http_base_url = url

    def user_base_url(self, skin_id: str) -> str:
        """用户皮肤资源基址（绝对 URL，经 sidecar 路由分发）。"""
        return f"{self._http_base_url}/user-skins/{skin_id}"

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_all(self) -> list[SkinSummary]:
        self.reload()  # 读时扫描：手动放置/外部变更即时可见，目录量小成本可忽略
        builtin = [
            manifest_to_summary(m, source="builtin", base_url=f"/skins/{m.id}")
            for m in BUILTIN_SKINS
        ]
        users = [
            manifest_to_summary(m, source="user", base_url=self.user_base_url(m.id))
            for m in self._user_skins.values()
        ]
        # 用户 id 与内置冲突时用户皮肤覆盖列表项（get 同口径），
        # 但内置模型文件仍在前端资产位，实践中 id 冲突属导入校验防区
        return builtin if not users else builtin + [u for u in users if u.id not in _BUILTIN_BY_ID]

    def get(self, skin_id: str) -> SkinManifest | None:
        if skin_id in _BUILTIN_BY_ID:
            return _BUILTIN_BY_ID[skin_id]
        self.reload()
        return self._user_skins.get(skin_id)

    def is_builtin(self, skin_id: str) -> bool:
        return skin_id in _BUILTIN_BY_ID

    def has(self, skin_id: str) -> bool:
        return self.get(skin_id) is not None

    # ------------------------------------------------------------------
    # 变更
    # ------------------------------------------------------------------

    def add_user_skin(self, manifest: SkinManifest) -> None:
        self._user_skins[manifest.id] = manifest

    def delete(self, skin_id: str) -> bool:
        """删除用户皮肤；返回目录是否被移除。"""
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
