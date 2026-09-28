"""skin manifest v2 `actions` 字段校验（M-A）。

覆盖：合法清单、缺字段向后兼容、动作 id 重复、未知通道、缺实现绑定、
fallback 指向未定义动作、fallback 链循环。
静态动作基线（default_static_actions）已随静态皮肤类型下线移除。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mochi_server.skin_manifest import (
    Live2dActionBinding,
    SkinAction,
    SkinManifest,
)


def _manifest(actions: list[SkinAction] | None = None, **kwargs) -> SkinManifest:
    payload = {
        "id": "test-skin",
        "name": "测试皮肤",
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
        **kwargs,
    }
    if actions is not None:
        payload["actions"] = [a.model_dump(by_alias=True, exclude_none=True) for a in actions]
    return SkinManifest.model_validate(payload)


def _action(action_id: str, **kwargs) -> SkinAction:
    kwargs.setdefault("live2d", {"motionGroups": ["Tap", "Idle"]})
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
    """live2d 实现绑定必填（static 绑定已随静态类型下线）。"""
    with pytest.raises(ValidationError) as exc:
        SkinAction.model_validate({"id": "wave", "channels": ["body"]})
    assert "live2d" in str(exc.value)


def test_static_binding_rejected() -> None:
    with pytest.raises(ValidationError):
        SkinAction.model_validate(
            {"id": "wave", "channels": ["body"], "static": {"animation": "wave"}}
        )


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


def test_terminal_action_fallback_rejected() -> None:
    """全链路兑底约束：idle_neutral 不得声明 fallback（用户清单亦不例外）。"""
    with pytest.raises(ValidationError) as exc:
        _manifest(actions=[_action("idle_neutral", fallback="nod"), _action("nod")])
    assert "兑底终点" in str(exc.value)


# ---------------------------------------------------------------------------
# live2d 绑定
# ---------------------------------------------------------------------------


def test_live2d_action_binding() -> None:
    """live2d 绑定：motionGroups 按偏好声明，expression 可选。"""
    action = SkinAction.model_validate(
        {
            "id": "wave",
            "channels": ["body", "face"],
            "live2d": {"motionGroups": ["Tap", "Idle"], "expression": "happy"},
        }
    )
    assert isinstance(action.live2d, Live2dActionBinding)
    assert action.live2d.motion_groups == ["Tap", "Idle"]
    assert action.live2d.expression == "happy"


# ---------------------------------------------------------------------------
# v3：声明式参数包络（paramEnvelope）与动作时长（durationMs）—— G3
# ---------------------------------------------------------------------------


def _envelope(**overrides) -> dict:
    payload = {
        "durationMs": 700,
        "keyframes": [{"param": "ParamEyeLOpen", "points": [[0, 1], [350, 0], [700, 1]]}],
    }
    payload.update(overrides)
    return payload


def test_v3_param_envelope_valid() -> None:
    """合法包络：camelCase alias 双向兼容，easing 缺省 linear。"""
    binding = Live2dActionBinding.model_validate({"paramEnvelope": _envelope()})
    env = binding.param_envelope
    assert env is not None
    assert env.duration_ms == 700
    assert env.easing == "linear"
    assert env.keyframes[0].param == "ParamEyeLOpen"


def test_v3_param_envelope_snake_case_also_accepted() -> None:
    binding = Live2dActionBinding.model_validate(
        {
            "param_envelope": {
                "duration_ms": 500,
                "keyframes": [{"param": "ParamEyeLOpen", "points": [[0, 1], [500, 1]]}],
            }
        }
    )
    assert binding.param_envelope is not None
    assert binding.param_envelope.duration_ms == 500


@pytest.mark.parametrize(
    "overrides",
    [
        {"durationMs": 0},  # 时长非正
        {"durationMs": 10_001},  # 超上限
        {"durationMs": 700, "easing": "bounce"},  # 非法 easing
        {"durationMs": 700, "keyframes": []},  # 空 keyframes
        {
            "durationMs": 700,
            "keyframes": [{"param": "P", "points": [[0, 1]]}],
        },  # 点数不足
        {
            "durationMs": 700,
            "keyframes": [{"param": "P", "points": [[100, 1], [700, 1]]}],
        },  # 首点不为 0
        {
            "durationMs": 700,
            "keyframes": [{"param": "P", "points": [[0, 1], [0, 1]]}],
        },  # 时间戳非严格递增
        {
            "durationMs": 700,
            "keyframes": [{"param": "P", "points": [[0, 99_999], [700, 1]]}],
        },  # 值超安全范围
        {
            "durationMs": 700,
            "keyframes": [{"param": "1bad", "points": [[0, 1], [700, 1]]}],
        },  # 参数 id 非法
        {
            "durationMs": 700,
            "keyframes": [
                {"param": "P", "points": [[0, 1], [700, 1]]},
                {"param": "P", "points": [[0, 0], [700, 0]]},
            ],
        },  # 参数重复
        {
            "durationMs": 500,
            "keyframes": [{"param": "P", "points": [[0, 1], [700, 1]]}],
        },  # 末点 ≠ durationMs
    ],
)
def test_v3_param_envelope_rejected(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        Live2dActionBinding.model_validate({"paramEnvelope": _envelope(**overrides)})


def test_v3_action_with_envelope_only_binding_and_duration() -> None:
    """包络-only 绑定 + 顶层 durationMs：完整的 v3 动作声明。"""
    action = SkinAction.model_validate(
        {
            "id": "custom_wink",
            "channels": ["body"],
            "agentSelectable": True,
            "durationMs": 700,
            "live2d": {"paramEnvelope": _envelope()},
        }
    )
    assert action.duration_ms == 700
    assert action.live2d.param_envelope is not None
    assert action.live2d.motion_groups == []


def test_v3_duration_ms_bounds() -> None:
    for bad in (0, -5, 10_001):
        with pytest.raises(ValidationError):
            SkinAction.model_validate(
                {
                    "id": "a",
                    "durationMs": bad,
                    "live2d": {"motionGroups": ["Tap"]},
                }
            )


def test_v3_envelope_action_in_manifest_roundtrip() -> None:
    """清单级：v3 动作在完整 manifest 中通过校验且 by_alias dump 保留 camelCase。"""
    manifest = _manifest(
        [
            SkinAction.model_validate(
                {
                    "id": "custom_wink",
                    "channels": ["body"],
                    "durationMs": 700,
                    "live2d": {"paramEnvelope": _envelope()},
                }
            )
        ]
    )
    dumped = manifest.model_dump(by_alias=True, exclude_none=True)
    entry = dumped["actions"][0]
    assert entry["durationMs"] == 700
    assert entry["live2d"]["paramEnvelope"]["durationMs"] == 700
