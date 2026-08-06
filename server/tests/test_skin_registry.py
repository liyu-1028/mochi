"""SkinRegistry 测试（M1-S1）：内置常量表 + 用户目录扫描 + default 解析。"""

from __future__ import annotations

import json

from mochi_server.paths import get_skins_dir
from mochi_server.skin.builtin import BUILTIN_SKINS
from mochi_server.skin.registry import SkinRegistry, resolve_skin_id


def _write_user_skin(skin_id: str, **over) -> None:
    skin_dir = get_skins_dir() / skin_id
    skin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"id": skin_id, "name": skin_id, "resourceType": "static", **over}
    (skin_dir / "skin.json").write_text(json.dumps(manifest), encoding="utf-8")


# ---------------------------------------------------------------------------
# default 别名
# ---------------------------------------------------------------------------


def test_resolve_skin_id_default():
    assert resolve_skin_id("default") == "hiyori"
    assert resolve_skin_id("mochi-julia") == "mochi-julia"


# ---------------------------------------------------------------------------
# 内置目录
# ---------------------------------------------------------------------------


def test_builtin_catalog_shape():
    assert set(BUILTIN_SKINS) == {"hiyori", "mochi-julia", "mochi-snj"}
    statics = [m for m in BUILTIN_SKINS.values() if m.resource_type == "static"]
    assert len(statics) >= 2, "3.2 验收：内置 ≥2 静态皮肤"
    for m in statics:
        assert m.image_file, "静态皮肤必须有 imageFile"
        assert m.animation.get("idle") is not None


def test_list_all_includes_builtin_with_relative_base_url():
    registry = SkinRegistry(http_base_url="http://127.0.0.1:8199")
    summaries = registry.list_all()
    assert len(summaries) >= 3
    hiyori = next(s for s in summaries if s.id == "hiyori")
    assert hiyori.source == "builtin"
    assert hiyori.resource_base_url == "/skins/hiyori"


# ---------------------------------------------------------------------------
# 用户目录扫描
# ---------------------------------------------------------------------------


def test_scan_user_skin():
    _write_user_skin("mycat", imageFile="avatar.png")
    registry = SkinRegistry(http_base_url="http://127.0.0.1:8199")

    summaries = registry.list_all()
    mycat = next((s for s in summaries if s.id == "mycat"), None)
    assert mycat is not None
    assert mycat.source == "user"
    assert mycat.resource_base_url == "http://127.0.0.1:8199/user-skins/mycat"
    assert registry.has("mycat")


def test_scan_skips_corrupt_manifest():
    broken = get_skins_dir() / "broken"
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "skin.json").write_text("{not json", encoding="utf-8")

    registry = SkinRegistry()
    assert not registry.has("broken")
    assert len(registry.list_all()) >= 3  # 内置仍在


# ---------------------------------------------------------------------------
# 删除
# ---------------------------------------------------------------------------


def test_delete_builtin_forbidden():
    registry = SkinRegistry()
    assert registry.delete("hiyori") is False
    assert registry.is_builtin("hiyori")


def test_delete_user_skin_removes_dir():
    _write_user_skin("gone", imageFile="a.png")
    registry = SkinRegistry()
    assert registry.has("gone")

    assert registry.delete("gone") is True
    assert not registry.has("gone")
    assert not (get_skins_dir() / "gone").exists()

    assert registry.delete("gone") is False  # 重复删除
