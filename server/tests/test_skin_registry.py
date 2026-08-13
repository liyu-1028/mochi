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
    assert resolve_skin_id("default") == "pikachu"
    assert resolve_skin_id("my-skin") == "my-skin"


# ---------------------------------------------------------------------------
# 内置目录
# ---------------------------------------------------------------------------


def test_builtin_catalog_shape():
    # 3.2：≥3 个静态皮肤（pokesprite 精灵图）
    assert set(BUILTIN_SKINS) == {"pikachu", "eevee", "snorlax"}
    for skin_id in ("pikachu", "eevee", "snorlax"):
        skin = BUILTIN_SKINS[skin_id]
        assert skin.resource_type == "static"
        assert skin.image_file
        assert skin.license  # 内置皮肤版权说明必填
        assert skin.animation and skin.emotion_mapping


def test_list_all_includes_builtin_with_relative_base_url():
    registry = SkinRegistry(http_base_url="http://127.0.0.1:8199")
    summaries = registry.list_all()
    assert len(summaries) >= 1
    pikachu = next(s for s in summaries if s.id == "pikachu")
    assert pikachu.source == "builtin"
    assert pikachu.resource_base_url == "/skins/pikachu"


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
    assert len(registry.list_all()) >= 1  # 内置仍在


# ---------------------------------------------------------------------------
# 删除
# ---------------------------------------------------------------------------


def test_delete_builtin_forbidden():
    registry = SkinRegistry()
    assert registry.delete("pikachu") is False
    assert registry.is_builtin("pikachu")


def test_delete_user_skin_removes_dir():
    _write_user_skin("gone", imageFile="a.png")
    registry = SkinRegistry()
    assert registry.has("gone")

    assert registry.delete("gone") is True
    assert not registry.has("gone")
    assert not (get_skins_dir() / "gone").exists()

    assert registry.delete("gone") is False  # 重复删除
