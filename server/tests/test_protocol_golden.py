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
    ACTION_CHANNELS,
    COMMAND_DATA_MODELS,
    COMMAND_TYPES,
    EVENT_DATA_MODELS,
    EVENT_TYPES,
    PROTOCOL_VERSION,
    SEMANTIC_ACTIONS,
    CharacterCueData,
    CharacterState,
    CompanionIntentData,
    CompanionSignalData,
    Emotion,
    RunFinishedData,
    RunStartedData,
    TextDeltaData,
    TextEndData,
    TextStartData,
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


# ---------------------------------------------------------------------------
# 语义动作注册表（M-A，协议规范 §11）：常量 vs 共享夹具
# TS 侧对应测试：packages/protocol/test/constants.test.ts
# ---------------------------------------------------------------------------

SEMANTIC_FIXTURE = GOLDEN_DIR / "semantic-actions.json"


def _load_semantic_fixture() -> dict:
    with SEMANTIC_FIXTURE.open(encoding="utf-8") as f:
        return json.load(f)


def test_semantic_actions_match_fixture() -> None:
    """SEMANTIC_ACTIONS 与共享夹具逐项一致（顺序敏感）。"""
    fixture = _load_semantic_fixture()
    assert list(SEMANTIC_ACTIONS) == fixture["semanticActions"]


def test_action_channels_match_fixture() -> None:
    """ACTION_CHANNELS 与共享夹具逐项一致（顺序敏感）。"""
    fixture = _load_semantic_fixture()
    assert list(ACTION_CHANNELS) == fixture["actionChannels"]


def test_semantic_actions_constraints() -> None:
    """词表约束：idle_neutral 必在（全链路兜底终点）、id 均为 snake_case。"""
    assert "idle_neutral" in SEMANTIC_ACTIONS
    import re

    for action_id in SEMANTIC_ACTIONS:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", action_id), action_id


# ---------------------------------------------------------------------------
# character.cue（M-C）：负载黄金夹具一致性
# ---------------------------------------------------------------------------

CUE_FIXTURE = GOLDEN_DIR / "character-cue.json"


def _load_cue_fixture() -> dict:
    with CUE_FIXTURE.open(encoding="utf-8") as f:
        return json.load(f)


def test_character_cue_type_registered() -> None:
    """EVENT_TYPES/EVENT_DATA_MODELS 注册 character.cue，夹具 type 一致。"""
    assert EVENT_TYPES["character.cue"] == "character.cue"
    assert EVENT_DATA_MODELS["character.cue"] is CharacterCueData
    fixture = _load_cue_fixture()
    assert fixture["event"]["type"] == "character.cue"


def test_character_cue_payload_matches_fixture() -> None:
    """夹具负载经 CharacterCueData 校验，camelCase 线上格式逐字段一致。"""
    fixture = _load_cue_fixture()
    data = CharacterCueData.model_validate(fixture["event"]["data"])
    wire = data.model_dump(by_alias=True, exclude_none=True)
    assert wire == fixture["event"]["data"]


def test_character_cue_enums_match_fixture() -> None:
    """cue 枚举字面量与夹具 expectedEnums 一致。"""
    from mochi_server.events import CUE_INTERRUPT_POLICY_VALUES, CUE_SOURCE_VALUES, CUE_SYNC_VALUES

    fixture = _load_cue_fixture()["expectedEnums"]
    assert list(CUE_SOURCE_VALUES) == fixture["CUE_SOURCES"]
    assert list(CUE_SYNC_VALUES) == fixture["CUE_SYNC"]
    assert list(CUE_INTERRUPT_POLICY_VALUES) == fixture["CUE_INTERRUPT_POLICIES"]


# ---------------------------------------------------------------------------
# companion.signal / companion.intent（M-D）：负载黄金夹具一致性
# ---------------------------------------------------------------------------
SIGNAL_FIXTURE = GOLDEN_DIR / "companion-signal.json"
INTENT_FIXTURE = GOLDEN_DIR / "companion-intent.json"
PROACTIVE_TURN = GOLDEN_DIR / "sequences" / "proactive-turn.jsonl"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_companion_signal_type_registered() -> None:
    """COMMAND_TYPES/COMMAND_DATA_MODELS 注册 companion.signal，夹具 type 一致。"""
    assert COMMAND_TYPES["companion.signal"] == "companion.signal"
    assert COMMAND_DATA_MODELS["companion.signal"] is CompanionSignalData
    fixture = _load_json(SIGNAL_FIXTURE)
    assert fixture["command"]["type"] == "companion.signal"


def test_companion_signal_payload_matches_fixture() -> None:
    """夹具负载经 CompanionSignalData 校验，camelCase 线上格式逐字段一致。"""
    fixture = _load_json(SIGNAL_FIXTURE)
    data = CompanionSignalData.model_validate(fixture["command"]["data"])
    wire = data.model_dump(by_alias=True, exclude_none=True)
    assert wire == fixture["command"]["data"]


def test_companion_signal_enums_match_fixture() -> None:
    """信号枚举字面量与夹具 expectedEnums 一致。"""
    from mochi_server.events import (
        INTENT_ACTIONS,
        INTENT_DECISIONS,
        INTENT_QUICK_REPLIES,
        MESSAGE_SOURCES,
        SIGNAL_KINDS,
        SIGNAL_SALIENCE,
    )

    fixture = _load_json(SIGNAL_FIXTURE)["expectedEnums"]
    assert list(SIGNAL_KINDS) == fixture["SIGNAL_KINDS"]
    assert list(SIGNAL_SALIENCE) == fixture["SIGNAL_SALIENCE"]
    assert list(INTENT_ACTIONS) == fixture["INTENT_ACTIONS"]
    assert list(INTENT_QUICK_REPLIES) == fixture["INTENT_QUICK_REPLIES"]
    assert list(INTENT_DECISIONS) == fixture["INTENT_DECISIONS"]
    assert list(MESSAGE_SOURCES) == fixture["MESSAGE_SOURCES"]


def test_companion_intent_type_registered() -> None:
    """EVENT_TYPES/EVENT_DATA_MODELS 注册 companion.intent，夹具 type 一致。"""
    assert EVENT_TYPES["companion.intent"] == "companion.intent"
    assert EVENT_DATA_MODELS["companion.intent"] is CompanionIntentData
    fixture = _load_json(INTENT_FIXTURE)
    assert fixture["event"]["type"] == "companion.intent"


def test_companion_intent_payload_matches_fixture() -> None:
    """夹具负载经 CompanionIntentData 校验，camelCase 线上格式逐字段一致。"""
    fixture = _load_json(INTENT_FIXTURE)
    data = CompanionIntentData.model_validate(fixture["event"]["data"])
    wire = data.model_dump(by_alias=True, exclude_none=True)
    assert wire == fixture["event"]["data"]


def test_proactive_turn_wire_sequence() -> None:
    """proactive 回合序列（run/text 事件族 source 字段族）逐帧校验。

    验收锚点（§8 决策点 4）：主动消息复用现有事件族 + source="proactive"，
    run.started.intentId 与 companion.intent.intentId 关联。
    """
    raw = PROACTIVE_TURN.read_text(encoding="utf-8")
    lines = [json.loads(line) for line in raw.splitlines() if line.strip()]
    types = [line["type"] for line in lines]
    assert types == [
        "run.started",
        "text.start",
        "text.delta",
        "text.delta",
        "text.end",
        "run.finished",
    ]
    for line in lines:
        if line["type"] == "run.started":
            data = RunStartedData.model_validate(line["data"])
            wire = data.model_dump(by_alias=True, exclude_none=True)
            assert wire["source"] == "proactive"
            assert wire["intentId"] == "intent-7a6b5c4d3e2f"
        elif line["type"] == "run.finished":
            RunFinishedData.model_validate(line["data"])
        else:
            model = {
                "text.start": TextStartData,
                "text.delta": TextDeltaData,
                "text.end": TextEndData,
            }[line["type"]]
            wire = model.model_validate(line["data"]).model_dump(by_alias=True, exclude_none=True)
            assert wire["source"] == "proactive"


def test_run_text_source_defaults_to_user() -> None:
    """缺省 source=user：既有帧格式不变（additive 兼容，零回归锚点）。"""
    assert RunStartedData(run_id="r", session_id="s").source == "user"
    assert TextDeltaData(run_id="r", message_id="m", delta="x").source == "user"
