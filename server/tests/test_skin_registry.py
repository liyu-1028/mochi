"""SkinRegistry 测试（M1-S1）：用户目录扫描 + 增删查。

内置静态皮肤常量表已随静态皮肤类型下线移除（2026-09-28）；
历史占位值 active_skin="default" 不再解析到任何皮肤。
"""

from __future__ import annotations

import json

from mochi_server.paths import get_skins_dir
from mochi_server.skin.registry import SkinRegistry


def _write_user_skin(skin_id: str, **over) -> None:
    skin_dir = get_skins_dir() / skin_id
    skin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": skin_id,
        "name": skin_id,
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
        **over,
    }
    (skin_dir / "skin.json").write_text(json.dumps(manifest), encoding="utf-8")


# ---------------------------------------------------------------------------
# 用户目录扫描
# ---------------------------------------------------------------------------


def test_scan_user_skin():
    _write_user_skin("mycat")
    registry = SkinRegistry(http_base_url="http://127.0.0.1:8199")

    summaries = registry.list_all()
    mycat = next((s for s in summaries if s.id == "mycat"), None)
    assert mycat is not None
    assert mycat.source == "user"
    assert mycat.resource_base_url == "http://127.0.0.1:8199/user-skins/mycat"
    assert registry.has("mycat")


def test_list_all_builtin_vrm_without_user_skins():
    """无用户皮肤时列表只含 Mochi 内置 VRM 角色（ADR-0011 D6 修订）。"""
    registry = SkinRegistry()
    summaries = registry.list_all()
    ids = [s.id for s in summaries]
    assert ids == ["mochi-vrm"]
    assert all(s.source == "builtin" and s.resource_base_url == f"/skins/{s.id}" for s in summaries)
    assert registry.is_builtin("mochi-vrm")
    assert not registry.has("seed-san")
    assert registry.get("mochi-vrm") is not None


def test_scan_skips_corrupt_manifest():
    broken = get_skins_dir() / "broken"
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "skin.json").write_text("{not json", encoding="utf-8")

    registry = SkinRegistry()
    assert not registry.has("broken")
    assert [s.id for s in registry.list_all()] == ["mochi-vrm"]


def test_get_unknown_skin_returns_none():
    """历史占位 "default" 已无对应皮肤。"""
    registry = SkinRegistry()
    assert registry.get("default") is None
    assert registry.has("default") is False


# ---------------------------------------------------------------------------
# 删除
# ---------------------------------------------------------------------------


def test_delete_user_skin_removes_dir():
    _write_user_skin("gone")
    registry = SkinRegistry()
    assert registry.has("gone")

    assert registry.delete("gone") is True
    assert not registry.has("gone")
    assert not (get_skins_dir() / "gone").exists()

    assert registry.delete("gone") is False  # 重复删除
