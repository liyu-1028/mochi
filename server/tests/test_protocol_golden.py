"""协议双端一致性测试（Python 侧）：黄金样例逐帧解析校验。

黄金样例为双端共享夹具（docs/specs/monorepo-structure.md §4）；
TS 侧对应测试：packages/protocol/test/golden.test.ts。
修改协议时必须同步更新双端测试与样例（scope=protocol 单提交）。
testdata/ 下所有 *.jsonl 自动纳入（M1-S4 起参数化扫描）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mochi_server.events import (
    COMMAND_DATA_MODELS,
    EVENT_DATA_MODELS,
    PROTOCOL_VERSION,
    CharacterState,
    Emotion,
    TextDeltaData,
    TextEndData,
    ToolConfirmData,
)

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "packages" / "protocol" / "testdata"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.jsonl"))

ALL_DATA_MODELS = {**COMMAND_DATA_MODELS, **EVENT_DATA_MODELS}


def _load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_golden_files_present() -> None:
    """至少存在既有两样例：工具回合 + 危险工具确认流。"""
    names = {p.name for p in GOLDEN_FILES}
    assert {"turn-with-tool-call.jsonl", "turn-with-tool-confirm.jsonl"} <= names


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=lambda p: p.name)
def test_envelope_shape(golden: Path) -> None:
    """每帧信封字段齐全，type 必须属于已注册类型。"""
    for frame in _load(golden):
        assert frame["v"] == PROTOCOL_VERSION
        assert frame["type"] in ALL_DATA_MODELS, f"未注册的事件类型：{frame['type']}"
        assert isinstance(frame["id"], str) and frame["id"]
        assert isinstance(frame["ts"], int)
        assert isinstance(frame["data"], dict)


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=lambda p: p.name)
def test_data_payloads_validate(golden: Path) -> None:
    """每帧 data 都能通过注册模型的 camelCase 校验（反序列化方向）。"""
    for frame in _load(golden):
        model = ALL_DATA_MODELS[frame["type"]]
        model.model_validate(frame["data"])


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=lambda p: p.name)
def test_turn_sequence(golden: Path) -> None:
    """回合时序骨架：hello → hello_ack → … → run.finished(complete)。"""
    frames = _load(golden)
    types = [f["type"] for f in frames]
    assert types[0] == "hello"
    assert types[1] == "hello_ack"
    assert "chat.send" in types
    assert types[-1] == "run.finished"
    assert frames[-1]["data"]["reason"] == "complete"


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=lambda p: p.name)
def test_text_deltas_concat_to_full_text(golden: Path) -> None:
    """text.delta 拼接必须等于 text.end.fullText（流式完整性）。"""
    frames = _load(golden)
    deltas = [
        TextDeltaData.model_validate(f["data"]).delta for f in frames if f["type"] == "text.delta"
    ]
    ends = [TextEndData.model_validate(f["data"]) for f in frames if f["type"] == "text.end"]
    assert len(ends) == 1
    assert "".join(deltas) == ends[0].full_text


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=lambda p: p.name)
def test_emotion_and_state_enums(golden: Path) -> None:
    """emotion / state.change 的取值必须落在协议枚举内。"""
    for f in _load(golden):
        if f["type"] == "emotion":
            Emotion(f["data"]["emotion"])
        elif f["type"] == "state.change":
            CharacterState(f["data"]["state"])


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=lambda p: p.name)
def test_confirm_flow_invariants(golden: Path) -> None:
    """确认流不变量（M1-S4，6.5）：requiresConfirmation 的工具调用必须有同
    toolCallId 的 tool.confirm 应答；deny → tool.call.end status=denied。"""
    frames = _load(golden)
    requires = {
        f["data"]["toolCallId"]
        for f in frames
        if f["type"] == "tool.call.start" and f["data"].get("requiresConfirmation")
    }
    confirms = {
        f["data"]["toolCallId"]: ToolConfirmData.model_validate(f["data"])
        for f in frames
        if f["type"] == "tool.confirm"
    }
    assert requires == set(confirms), "须确认的工具调用与确认应答一一对应"
    for tool_call_id, confirm in confirms.items():
        end = next(
            (
                f["data"]
                for f in frames
                if f["type"] == "tool.call.end" and f["data"]["toolCallId"] == tool_call_id
            ),
            None,
        )
        assert end is not None
        expected = "denied" if confirm.decision == "deny" else "success"
        assert end["status"] == expected


# ---------------------------------------------------------------------------
# tool.confirm 命令负载（M1-S4 契约层）
# ---------------------------------------------------------------------------


def test_tool_confirm_decision_enum_and_default() -> None:
    payload = ToolConfirmData.model_validate(
        {"runId": "r1", "toolCallId": "tc1", "decision": "allow"}
    )
    assert payload.remember is False  # 缺省不进白名单
    dumped = payload.model_dump(by_alias=True)
    assert set(dumped) == {"runId", "toolCallId", "decision", "remember"}

    with pytest.raises(ValidationError):
        ToolConfirmData.model_validate({"runId": "r1", "toolCallId": "tc1", "decision": "maybe"})
