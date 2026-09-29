"""skin_manifest v3（声明式参数包络与动作）边界与极限测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mochi_server.skin_manifest import (
    ENVELOPE_DURATION_MAX_MS,
    ENVELOPE_VALUE_LIMIT,
    ParamEnvelope,
    SkinAction,
)


def _envelope(duration_ms: int = 700, keyframes: list | None = None, **kwargs) -> dict:
    if keyframes is None:
        keyframes = [
            {"param": "ParamEyeLOpen", "points": [[0, 1.0], [350, 0.0], [duration_ms, 1.0]]}
        ]
    payload = {"durationMs": duration_ms, "keyframes": keyframes, **kwargs}
    return payload


# ---------------------------------------------------------------------------
# 1. 多轨道关键帧末点与时间戳边界
# ---------------------------------------------------------------------------


def test_multi_keyframe_all_tracks_must_end_at_duration() -> None:
    """严厉测试：多轨道参数时，不仅第一轨，每一轨的末点时间都必须等于 durationMs。"""
    # 第一轨合法(700)，第二轨末点为 500 (≠ 700)
    payload = _envelope(
        duration_ms=700,
        keyframes=[
            {"param": "ParamEyeLOpen", "points": [[0, 1.0], [700, 1.0]]},
            {"param": "ParamMouthForm", "points": [[0, 0.0], [500, 0.5]]},
        ],
    )
    with pytest.raises(ValidationError) as exc:
        ParamEnvelope.model_validate(payload)
    assert "末点" in str(exc.value)


def test_multi_keyframe_second_track_exceeds_duration_rejected() -> None:
    """严厉测试：第二轨末点超过 durationMs (900 > 700) 必须被拒绝。"""
    payload = _envelope(
        duration_ms=700,
        keyframes=[
            {"param": "ParamEyeLOpen", "points": [[0, 1.0], [700, 1.0]]},
            {"param": "ParamMouthForm", "points": [[0, 0.0], [900, 0.5]]},
        ],
    )
    with pytest.raises(ValidationError) as exc:
        ParamEnvelope.model_validate(payload)
    assert "末点" in str(exc.value)


def test_multi_keyframe_all_valid() -> None:
    """合法多轨道参数：所有轨道均首点为 0、末点为 durationMs。"""
    payload = _envelope(
        duration_ms=700,
        keyframes=[
            {"param": "ParamEyeLOpen", "points": [[0, 1.0], [350, 0.0], [700, 1.0]]},
            {"param": "ParamMouthForm", "points": [[0, 0.0], [200, 0.6], [700, 0.0]]},
            {"param": "ParamAngleZ", "points": [[0, 0.0], [700, 5.0]]},
        ],
    )
    env = ParamEnvelope.model_validate(payload)
    assert len(env.keyframes) == 3
    assert env.duration_ms == 700


# ---------------------------------------------------------------------------
# 2. 数值与时长极值边界
# ---------------------------------------------------------------------------


def test_duration_boundary_min_and_max() -> None:
    """时长边界：1ms 与 10000ms 合法；0ms 与 10001ms 拒绝。"""
    # 1ms
    env_1 = ParamEnvelope.model_validate(
        _envelope(duration_ms=1, keyframes=[{"param": "P", "points": [[0, 0], [1, 1]]}])
    )
    assert env_1.duration_ms == 1

    # 10000ms
    env_max = ParamEnvelope.model_validate(
        _envelope(
            duration_ms=ENVELOPE_DURATION_MAX_MS,
            keyframes=[{"param": "P", "points": [[0, 0], [ENVELOPE_DURATION_MAX_MS, 1]]}],
        )
    )
    assert env_max.duration_ms == ENVELOPE_DURATION_MAX_MS

    # 0ms 拒绝
    with pytest.raises(ValidationError):
        ParamEnvelope.model_validate(
            _envelope(duration_ms=0, keyframes=[{"param": "P", "points": [[0, 0], [0, 1]]}])
        )

    # 10001ms 拒绝
    with pytest.raises(ValidationError):
        ParamEnvelope.model_validate(
            _envelope(
                duration_ms=ENVELOPE_DURATION_MAX_MS + 1,
                keyframes=[{"param": "P", "points": [[0, 0], [ENVELOPE_DURATION_MAX_MS + 1, 1]]}],
            )
        )


def test_value_limit_boundaries() -> None:
    """值域安全范围边界：±10000 合法；±10000.1 拒绝。"""
    # 正极限 10000.0
    valid_pos = ParamEnvelope.model_validate(
        _envelope(
            duration_ms=100,
            keyframes=[{"param": "P", "points": [[0, 0.0], [100, float(ENVELOPE_VALUE_LIMIT)]]}],
        )
    )
    assert valid_pos.keyframes[0].points[1][1] == ENVELOPE_VALUE_LIMIT

    # 负极限 -10000.0
    valid_neg = ParamEnvelope.model_validate(
        _envelope(
            duration_ms=100,
            keyframes=[{"param": "P", "points": [[0, 0.0], [100, -float(ENVELOPE_VALUE_LIMIT)]]}],
        )
    )
    assert valid_neg.keyframes[0].points[1][1] == -ENVELOPE_VALUE_LIMIT

    # 超正极限 10000.1
    with pytest.raises(ValidationError) as exc1:
        ParamEnvelope.model_validate(
            _envelope(
                duration_ms=100,
                keyframes=[
                    {"param": "P", "points": [[0, 0.0], [100, float(ENVELOPE_VALUE_LIMIT) + 0.1]]}
                ],
            )
        )
    assert "超出安全范围" in str(exc1.value)

    # 超负极限 -10000.1
    with pytest.raises(ValidationError) as exc2:
        ParamEnvelope.model_validate(
            _envelope(
                duration_ms=100,
                keyframes=[
                    {"param": "P", "points": [[0, 0.0], [100, -float(ENVELOPE_VALUE_LIMIT) - 0.1]]}
                ],
            )
        )
    assert "超出安全范围" in str(exc2.value)


# ---------------------------------------------------------------------------
# 3. 时间戳严格递增与非数字/NaN/布尔防注入
# ---------------------------------------------------------------------------


def test_timestamp_non_increasing_rejected() -> None:
    """时间戳倒流或相等必须拒绝。"""
    # 相等
    with pytest.raises(ValidationError) as exc1:
        ParamEnvelope.model_validate(
            _envelope(
                duration_ms=100,
                keyframes=[{"param": "P", "points": [[0, 0], [50, 1], [50, 2], [100, 0]]}],
            )
        )
    assert "严格递增" in str(exc1.value)

    # 倒流
    with pytest.raises(ValidationError) as exc2:
        ParamEnvelope.model_validate(
            _envelope(
                duration_ms=100,
                keyframes=[{"param": "P", "points": [[0, 0], [60, 1], [40, 2], [100, 0]]}],
            )
        )
    assert "严格递增" in str(exc2.value)


def test_skin_action_duration_ms_boundary() -> None:
    """SkinAction.duration_ms 边界测试。"""
    # 1ms 合法
    a1 = SkinAction.model_validate(
        {"id": "test_act", "durationMs": 1, "live2d": {"motionGroups": ["Tap"]}}
    )
    assert a1.duration_ms == 1

    # 10000ms 合法
    a2 = SkinAction.model_validate(
        {
            "id": "test_act",
            "durationMs": ENVELOPE_DURATION_MAX_MS,
            "live2d": {"motionGroups": ["Tap"]},
        }
    )
    assert a2.duration_ms == ENVELOPE_DURATION_MAX_MS

    # 0ms 拒绝
    with pytest.raises(ValidationError):
        SkinAction.model_validate(
            {"id": "test_act", "durationMs": 0, "live2d": {"motionGroups": ["Tap"]}}
        )

    # 10001ms 拒绝
    with pytest.raises(ValidationError):
        SkinAction.model_validate(
            {
                "id": "test_act",
                "durationMs": ENVELOPE_DURATION_MAX_MS + 1,
                "live2d": {"motionGroups": ["Tap"]},
            }
        )
