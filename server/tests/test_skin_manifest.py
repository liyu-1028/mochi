"""skin.json 清单模型测试（功能清单 3.1）：校验/默认值/别名。

静态皮肤类型已下线（2026-09-28）：resourceType 仅接受 live2d，
imageFile/animation/emotionMapping 字段随之移除。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mochi_server.skin_manifest import (
    SkinManifest,
    SkinSummary,
    manifest_to_summary,
)


def _minimal(**over) -> dict:
    return {
        "id": "t",
        "name": "T",
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
        **over,
    }


# ---------------------------------------------------------------------------
# 校验与默认值
# ---------------------------------------------------------------------------


def test_minimal_manifest_defaults():
    m = SkinManifest.model_validate(_minimal())
    assert m.resource_type == "live2d"
    assert m.version == "1.0.0"
    assert m.capabilities.motion_groups == []
    assert m.capabilities.expressions == []
    assert m.credits == {}


def test_id_pattern_enforced():
    for bad in ("UPPER", "-leading", "with_underscore", "a" * 33, ""):
        with pytest.raises(ValidationError):
            SkinManifest.model_validate(_minimal(id=bad))
    for good in ("a", "mochi-julia", "live2d-hiyori"):
        assert SkinManifest.model_validate(_minimal(id=good)).id == good


def test_resource_type_static_rejected():
    """静态类型已下线：不再接受 static。"""
    with pytest.raises(ValidationError):
        SkinManifest.model_validate(_minimal(resourceType="static"))
    with pytest.raises(ValidationError):
        SkinManifest.model_validate(_minimal(resourceType="spine"))


def test_model_file_required():
    with pytest.raises(ValidationError):
        SkinManifest.model_validate({"id": "t", "name": "T", "resourceType": "live2d"})


def test_camel_and_snake_case_both_accepted():
    by_camel = SkinManifest.model_validate(
        _minimal(cubismVersion=4, capabilities={"motionGroups": ["Idle"]})
    )
    assert by_camel.cubism_version == 4
    assert by_camel.capabilities.motion_groups == ["Idle"]

    by_snake = SkinManifest.model_validate(
        {"id": "t", "name": "T", "resource_type": "live2d", "model_file": "m.model3.json"}
    )
    assert by_snake.model_file == "m.model3.json"


# ---------------------------------------------------------------------------
# 序列化与摘要
# ---------------------------------------------------------------------------


def test_dump_by_alias_roundtrip():
    m = SkinManifest.model_validate(_minimal(license="MIT"))
    dumped = m.model_dump(by_alias=True, exclude_none=True)
    assert dumped["resourceType"] == "live2d"
    assert dumped["modelFile"] == "m.model3.json"
    # 别名输出可再读回
    assert SkinManifest.model_validate(dumped).id == "t"


def test_manifest_to_summary():
    m = SkinManifest.model_validate(_minimal(license="MIT", credits={"model": "X"}))
    s = manifest_to_summary(m, source="user", base_url="http://127.0.0.1:8199/user-skins/t")
    assert isinstance(s, SkinSummary)
    assert s.source == "user"
    assert s.resource_base_url.endswith("/user-skins/t")
    dumped = s.model_dump(by_alias=True)
    assert dumped["resourceBaseUrl"] == s.resource_base_url
    assert dumped["resourceType"] == "live2d"


def test_summary_carries_full_manifest_for_rendering():
    """前端渲染依赖清单字段：摘要必须带全量清单（回归防线）。"""
    m = SkinManifest.model_validate(
        _minimal(
            capabilities={"motionGroups": ["Idle", "TapBody"]},
            actions=[
                {
                    "id": "flick_head",
                    "live2d": {"motionGroups": ["Tap"]},
                    "agentSelectable": True,
                }
            ],
        )
    )
    dumped = manifest_to_summary(
        m, source="user", base_url="http://127.0.0.1:8199/user-skins/t"
    ).model_dump(by_alias=True, exclude_none=True)
    assert dumped["capabilities"]["motionGroups"] == ["Idle", "TapBody"]
    assert dumped["actions"][0]["live2d"]["motionGroups"] == ["Tap"]


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
