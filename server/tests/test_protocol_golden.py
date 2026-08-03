"""协议双端一致性测试（Python 侧）：黄金样例逐帧解析校验。

黄金样例为双端共享夹具（docs/specs/monorepo-structure.md §4）；
TS 侧对应测试：packages/protocol/test/golden.test.ts。
修改协议时必须同步更新双端测试与样例（scope=protocol 单提交）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mochi_server.events import (
    COMMAND_DATA_MODELS,
    EVENT_DATA_MODELS,
    PROTOCOL_VERSION,
    CharacterState,
    Emotion,
    TextDeltaData,
    TextEndData,
)

GOLDEN_FILE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "protocol"
    / "testdata"
    / "turn-with-tool-call.jsonl"
)

ALL_DATA_MODELS = {**COMMAND_DATA_MODELS, **EVENT_DATA_MODELS}


@pytest.fixture(scope="module")
def frames() -> list[dict]:
    with GOLDEN_FILE.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_golden_file_exists() -> None:
    assert GOLDEN_FILE.exists(), f"黄金样例缺失：{GOLDEN_FILE}"


def test_envelope_shape(frames: list[dict]) -> None:
    """每帧信封字段齐全，type 必须属于已注册类型。"""
    for frame in frames:
        assert frame["v"] == PROTOCOL_VERSION
        assert frame["type"] in ALL_DATA_MODELS, f"未注册的事件类型：{frame['type']}"
        assert isinstance(frame["id"], str) and frame["id"]
        assert isinstance(frame["ts"], int)
        assert isinstance(frame["data"], dict)


def test_data_payloads_validate(frames: list[dict]) -> None:
    """每帧 data 都能通过注册模型的 camelCase 校验（反序列化方向）。"""
    for frame in frames:
        model = ALL_DATA_MODELS[frame["type"]]
        model.model_validate(frame["data"])


def test_turn_sequence(frames: list[dict]) -> None:
    """回合时序骨架：hello → hello_ack → … → run.finished(complete)。"""
    types = [f["type"] for f in frames]
    assert types[0] == "hello"
    assert types[1] == "hello_ack"
    assert "chat.send" in types
    assert types[-1] == "run.finished"
    assert frames[-1]["data"]["reason"] == "complete"


def test_text_deltas_concat_to_full_text(frames: list[dict]) -> None:
    """text.delta 拼接必须等于 text.end.fullText（流式完整性）。"""
    deltas = [
        TextDeltaData.model_validate(f["data"]).delta for f in frames if f["type"] == "text.delta"
    ]
    ends = [TextEndData.model_validate(f["data"]) for f in frames if f["type"] == "text.end"]
    assert len(ends) == 1
    assert "".join(deltas) == ends[0].full_text


def test_emotion_and_state_enums(frames: list[dict]) -> None:
    """emotion / state.change 的取值必须落在协议枚举内。"""
    for f in frames:
        if f["type"] == "emotion":
            Emotion(f["data"]["emotion"])
        elif f["type"] == "state.change":
            CharacterState(f["data"]["state"])
