"""skin manifest v2 `actions` 字段校验（M-A）。

覆盖：合法清单、缺字段向后兼容、动作 id 重复、未知通道、缺实现绑定、
fallback 指向未定义动作、fallback 链循环、default_static_actions 基线、
内置皮肤登记、importer 生成清单带动作。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mochi_server.events import SEMANTIC_ACTIONS
from mochi_server.skin.builtin import BUILTIN_SKINS
from mochi_server.skin_manifest import (
    SkinAction,
    SkinManifest,
    default_static_actions,
)


def _manifest(actions: list[SkinAction] | None = None, **kwargs) -> SkinManifest:
    payload = {
        "id": "test-skin",
        "name": "测试皮肤",
        "resourceType": "static",
        "imageFile": "avatar.png",
        **kwargs,
    }
    if actions is not None:
        payload["actions"] = [a.model_dump(by_alias=True, exclude_none=True) for a in actions]
    return SkinManifest.model_validate(payload)


def _action(action_id: str, **kwargs) -> SkinAction:
    kwargs.setdefault("static", {"animation": action_id})
    return SkinAction.model_validate({"id": action_id, **kwargs})


# ---------------------------------------------------------------------------
# 向后兼容
# ---------------------------------------------------------------------------


def test_v1_manifest_without_actions_still_valid() -> None:
    """旧皮肤（无 actions 字段）照常通过，默认空列表。"""
    manifest = _manifest()
    assert manifest.actions == []


# ---------------------------------------------------------------------------
# 合法场景
# ---------------------------------------------------------------------------


def test_valid_actions_with_local_fallback_chain() -> None:
    """合法链：celebrate → nod → idle_neutral（终点无 fallback）。"""
    actions = [
        _action("idle_neutral"),
        _action("nod", fallback="idle_neutral"),
        _action("celebrate", fallback="nod", priority=60, cooldownMs=10_000),
    ]
    manifest = _manifest(actions=actions)
    assert [a.id for a in manifest.actions] == ["idle_neutral", "nod", "celebrate"]
    assert manifest.actions[2].cooldown_ms == 10_000
    assert manifest.actions[2].interrupt_policy == "replace"


def test_fallback_to_semantic_vocabulary_is_legal() -> None:
    """fallback 可直接指向语义词表（前端内置兜底接手）。"""
    manifest = _manifest(actions=[_action("my_wave", fallback="wave")])
    assert manifest.actions[0].fallback == "wave"


def test_agent_selectable_defaults_false() -> None:
    """白名单铁律：缺省不可被模型选择。"""
    assert _action("wave").agent_selectable is False


# ---------------------------------------------------------------------------
# 校验失败场景（422 可读文案）
# ---------------------------------------------------------------------------


def test_duplicate_action_ids_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        _manifest(actions=[_action("wave"), _action("wave")])
    assert "动作 id 重复" in str(exc.value)


def test_unknown_channel_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        _action("wave", channels=["teleport"])
    assert "未知通道" in str(exc.value)


def test_missing_binding_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        SkinAction.model_validate({"id": "wave", "channels": ["body"]})
    assert "缺少 live2d/static 任一实现绑定" in str(exc.value)


def test_fallback_to_undefined_action_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        _manifest(actions=[_action("wave", fallback="does_not_exist")])
    assert "fallback 指向未定义动作" in str(exc.value)


def test_fallback_cycle_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        _manifest(
            actions=[
                _action("a", fallback="b"),
                _action("b", fallback="c"),
                _action("c", fallback="a"),
            ]
        )
    assert "循环" in str(exc.value)


def test_self_fallback_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        _manifest(actions=[_action("wave", fallback="wave")])
    assert "循环" in str(exc.value)


# ---------------------------------------------------------------------------
# 基线与内置登记
# ---------------------------------------------------------------------------


def test_default_static_actions_baseline() -> None:
    """基线 10 项（刻意不含 think/listen）；除 idle_neutral 外均可被模型选择。"""
    actions = default_static_actions()
    ids = {a.id for a in actions}
    assert len(actions) == 10
    assert "think" not in ids and "listen" not in ids
    assert ids <= set(SEMANTIC_ACTIONS)
    for action in actions:
        if action.id == "idle_neutral":
            assert action.fallback is None and action.agent_selectable is False
        else:
            assert action.fallback == "idle_neutral"
            assert action.agent_selectable is True


def test_builtin_skins_carry_actions() -> None:
    for manifest in BUILTIN_SKINS.values():
        ids = [a.id for a in manifest.actions]
        assert "idle_neutral" in ids, manifest.id


def test_live2d_action_binding() -> None:
    """live2d 绑定：motionGroups 按偏好声明，expression 可选。"""
    action = SkinAction.model_validate(
        {
            "id": "wave",
            "channels": ["body", "face"],
            "live2d": {"motionGroups": ["Tap", "Idle"], "expression": "happy"},
        }
    )
    assert action.live2d is not None
    assert action.live2d.motion_groups == ["Tap", "Idle"]
    assert action.live2d.expression == "happy"
