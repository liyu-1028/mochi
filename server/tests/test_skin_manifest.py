"""skin.json v1 清单模型测试（功能清单 3.1）：校验/默认值/别名/hiyori 读回。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mochi_server.skin_manifest import (
    AnimationParams,
    SkinManifest,
    SkinSummary,
    manifest_to_summary,
)

HIYORI_SKIN_JSON = Path(__file__).parents[2] / "assets" / "skins" / "hiyori" / "skin.json"


def _minimal(**over) -> dict:
    return {"id": "t", "name": "T", "resourceType": "static", **over}


# ---------------------------------------------------------------------------
# 校验与默认值
# ---------------------------------------------------------------------------


def test_minimal_static_manifest_defaults():
    m = SkinManifest.model_validate(_minimal())
    assert m.resource_type == "static"
    assert m.version == "1.0.0"
    assert m.capabilities.motion_groups == []
    assert m.capabilities.expressions == []
    assert m.animation == {}
    assert m.emotion_mapping == {}
    assert m.credits == {}


def test_id_pattern_enforced():
    for bad in ("UPPER", "-leading", "with_underscore", "a" * 33, ""):
        with pytest.raises(ValidationError):
            SkinManifest.model_validate(_minimal(id=bad))
    for good in ("a", "mochi-julia", "png-abc123def456"):
        assert SkinManifest.model_validate(_minimal(id=good)).id == good


def test_resource_type_literal_enforced():
    with pytest.raises(ValidationError):
        SkinManifest.model_validate(_minimal(resourceType="spine"))


def test_emotion_scale_bounds():
    with pytest.raises(ValidationError):
        SkinManifest.model_validate(_minimal(emotionMapping={"happy": {"scale": 3.0}}))


def test_camel_and_snake_case_both_accepted():
    by_camel = SkinManifest.model_validate(
        _minimal(imageFile="a.png", capabilities={"motionGroups": ["Idle"]})
    )
    assert by_camel.image_file == "a.png"
    assert by_camel.capabilities.motion_groups == ["Idle"]

    by_snake = SkinManifest.model_validate(
        {"id": "t", "name": "T", "resource_type": "static", "image_file": "a.png"}
    )
    assert by_snake.image_file == "a.png"


def test_animation_state_defaults_filled():
    m = SkinManifest.model_validate(_minimal(animation={"idle": {"float": True}}))
    assert m.animation["idle"] == AnimationParams(float=True, breathe=False, sway=False)


# ---------------------------------------------------------------------------
# 序列化与摘要
# ---------------------------------------------------------------------------


def test_dump_by_alias_roundtrip():
    m = SkinManifest.model_validate(_minimal(imageFile="a.png"))
    dumped = m.model_dump(by_alias=True, exclude_none=True)
    assert dumped["resourceType"] == "static"
    assert dumped["imageFile"] == "a.png"
    assert "modelFile" not in dumped
    # 别名输出可再读回
    assert SkinManifest.model_validate(dumped).id == "t"


def test_manifest_to_summary():
    m = SkinManifest.model_validate(_minimal(license="MIT", credits={"illustration": "X"}))
    s = manifest_to_summary(m, source="user", base_url="http://127.0.0.1:8199/user-skins/t")
    assert isinstance(s, SkinSummary)
    assert s.source == "user"
    assert s.resource_base_url.endswith("/user-skins/t")
    dumped = s.model_dump(by_alias=True)
    assert dumped["resourceBaseUrl"] == s.resource_base_url
    assert dumped["resourceType"] == "static"


def test_summary_carries_full_manifest_for_rendering():
    """前端双路径渲染依赖清单字段：摘要必须带全量清单（回归防线）。"""
    m = SkinManifest.model_validate(
        _minimal(
            imageFile="avatar.png",
            capabilities={"motionGroups": ["Idle"]},
            animation={"idle": {"float": True}},
        )
    )
    dumped = manifest_to_summary(
        m, source="user", base_url="http://127.0.0.1:8199/user-skins/t"
    ).model_dump(by_alias=True, exclude_none=True)
    assert dumped["imageFile"] == "avatar.png"
    assert dumped["capabilities"]["motionGroups"] == ["Idle"]
    assert dumped["animation"]["idle"]["float"] is True


# ---------------------------------------------------------------------------
# hiyori 内置清单读回（v1 升级后）
# ---------------------------------------------------------------------------


def test_hiyori_skin_json_loads_as_v1():
    raw = json.loads(HIYORI_SKIN_JSON.read_text(encoding="utf-8"))
    m = SkinManifest.model_validate(raw)
    assert m.id == "hiyori"
    assert m.resource_type == "live2d"
    assert m.model_file == "hiyori_pro_t11.model3.json"
    assert "Idle" in m.capabilities.motion_groups
    assert len(m.capabilities.motion_groups) >= 7


def test_m0_minimal_manifest_still_loads():
    """M0-S3 最小清单（仅展示字段）向后兼容：缺能力字段不报错。"""
    raw = {
        "id": "legacy",
        "name": "Legacy",
        "version": "1.0.0",
        "resourceType": "live2d",
        "license": "X",
        "modelFile": "m.model3.json",
        "cubismVersion": 3,
    }
    m = SkinManifest.model_validate(raw)
    assert m.capabilities.motion_groups == []
