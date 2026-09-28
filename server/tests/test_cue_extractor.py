"""CueStreamParser（M-C）单测 + LLMAgentService cue 路径集成测试。

验收锚点（rollout plan M-C）：
- 控制标记零泄漏：畸形/半畸形标记绝不进入可见文本（气泡/TTS/落盘）；
- 白名单强校验：非 agentSelectable / 未知 id 丢弃 + 计数可观测；
- sentenceIndex 按生成时分句边界编号；
- cue 路径关闭 = M-B 行为（标记解析完全旁路——标记原样进文本，由
  prompt 缺席保证模型不产出，路径本身零介入）。
"""

from __future__ import annotations

from typing import Any

import pytest
from fakes import ScriptedChatModel, make_test_adapter
from langchain_core.messages import AIMessageChunk

from mochi_server.agent import LLMAgentService
from mochi_server.agent.cue_extractor import CueStreamParser, cue_prompt_section
from mochi_server.agent.service import AgentContext
from mochi_server.skin_manifest import SkinManifest

# ---------------------------------------------------------------------------
# CueStreamParser 单测
# ---------------------------------------------------------------------------


def _texts(outputs) -> str:
    return "".join(o.text for o in outputs if o.kind == "text")


def _cues(outputs):
    return [o.cue for o in outputs if o.kind == "cue"]


def test_clean_tag_extracted_and_stripped() -> None:
    p = CueStreamParser("r", "m")
    outs = p.feed("你好！[[cue:happy]]很高兴见到你。")
    assert _texts(outs) == "你好！很高兴见到你。"  # 标记消失，其余原样
    cues = _cues(outs)
    assert len(cues) == 1
    assert cues[0].channels.face is not None
    assert cues[0].channels.face.emotion == "happy"
    assert cues[0].channels.body is None
    assert cues[0].source == "reply"
    assert cues[0].priority == 45
    assert cues[0].interrupt_policy == "replace"
    assert cues[0].ttl_ms == 15_000


def test_body_cue_and_sentence_numbering() -> None:
    p = CueStreamParser("r", "m")
    outs = p.feed("第一句。[[cue:comfort]]第二句！[[cue:nod]]第三句")
    cues = _cues(outs)
    assert [c.channels.body.action_id for c in cues] == ["comfort", "nod"]
    # 标记前已完成分句数 + 1：comfort 在第 2 句开头、nod 在第 3 句开头
    assert [c.sentence_index for c in cues] == [2, 3]


def test_tag_at_stream_start_is_speech_start() -> None:
    p = CueStreamParser("r", "m")
    outs = p.feed("[[cue:wave]]你好呀！")
    cues = _cues(outs)
    assert cues[0].sync == "speech_start"
    assert cues[0].sentence_index == 1
    assert _texts(outs) == "你好呀！"


def test_tag_split_across_chunks_no_leak() -> None:
    p = CueStreamParser("r", "m")
    texts = ""
    cues = []
    for delta in ["开头[[cu", "e:hap", "py]]后续正文"]:
        outs = p.feed(delta)
        texts += _texts(outs)
        cues += _cues(outs)
    texts += _texts(p.flush())
    assert texts == "开头后续正文"  # 标记碎片零泄漏
    assert len(cues) == 1 and cues[0].channels.face.emotion == "happy"


@pytest.mark.parametrize(
    "malformed",
    [
        "[[cue:",  # 流末未闭合
        "[[cue:happ",  # id 截断
        "[[cue:]]",  # 空 id
        "[[cue:UNKNOWN_ID]]",  # 非法字符（大写/词表外）
        "[[cue happy]]",  # 缺冒号
        "[[CUE:happy]]",  # 大写关键字
    ],
)
def test_malformed_tags_never_leak(malformed: str) -> None:
    """对抗样本：畸形/半畸形标记整段丢弃，绝不进入可见文本。"""
    p = CueStreamParser("r", "m")
    outs = p.feed(f"前文{malformed}后文")
    outs += p.flush()
    assert malformed not in _texts(outs)
    assert "[[cue" not in _texts(outs).lower().replace(" ", "")
    assert _cues(outs) == []


def test_unterminated_tag_keeps_trailing_text() -> None:
    """流末未闭合标记：只丢标记残骸，其后正文保留（审查修复 2026-09-28）。

    cues 默认 auto——小模型输出畸形标记是常态，整段丢弃会造成回复截断。
    """
    p = CueStreamParser("r", "m")
    outs = p.feed("第一句。[[cue:sad 我很难过，因为没解决。")
    outs += p.flush()
    assert _texts(outs) == "第一句。 我很难过，因为没解决。"
    assert _cues(outs) == []  # 不产生 cue（id 非法）
    assert p.dropped.get("malformed_tag") == 1


def test_bad_id_with_close_keeps_trailing_text() -> None:
    """非法 id 且已闭合：丢到 ]] 为止，其后正文保留。"""
    p = CueStreamParser("r", "m")
    outs = p.feed("正文[[cue:BAD]]保留我")
    outs += p.flush()
    assert _texts(outs) == "正文保留我"
    assert _cues(outs) == []


def test_extra_bracket_tolerated() -> None:
    """[[ cue : happy ]]]：宽容解析为合法 cue，仅多余 ] 字符放行（标记本体零泄漏）。"""
    p = CueStreamParser("r", "m")
    outs = p.feed("[[ cue : happy ]]]好")
    assert len(_cues(outs)) == 1
    assert _texts(outs) == "]好"


def test_non_tag_brackets_pass_through() -> None:
    """与标记无关的 [[…]]（如 markdown 脚注）原样保留。"""
    p = CueStreamParser("r", "m")
    outs = p.feed("参见[[code]]说明")
    outs += p.flush()
    assert _texts(outs) == "参见[[code]]说明"


def test_unknown_action_dropped_with_counter() -> None:
    p = CueStreamParser("r", "m")
    outs = p.feed("正文[[cue:dance]]继续")
    assert _cues(outs) == []
    assert p.dropped.get("unknown_action") == 1


def test_terminal_action_never_selectable() -> None:
    p = CueStreamParser("r", "m")
    outs = p.feed("正文[[cue:idle_neutral]]继续")
    assert _cues(outs) == []
    assert p.dropped.get("unknown_action") == 1  # 非 agentSelectable


def test_cue_cap_per_reply() -> None:
    p = CueStreamParser("r", "m")
    text = "".join(f"第{i}句。[[cue:happy]]" for i in range(12))
    cues = _cues(p.feed(text)) + _cues(p.flush())
    assert len(cues) == 8
    assert p.dropped.get("cap_reached") == 4


def test_stage_direction_inside_parens_does_not_count_boundary() -> None:
    """M-F：全角括号内终止符不计入分句（与 TTS 剥离口径一致）。"""
    p = CueStreamParser("r", "m")
    # 指示内的「！」不产生边界；标记仍在第 2 句开头
    outs = p.feed("第一句。（好笑！）[[cue:nod]]第二句")
    cues = _cues(outs)
    assert len(cues) == 1
    assert cues[0].sentence_index == 2
    assert _texts(outs) == "第一句。（好笑！）第二句"  # 括号文本原样保留


def test_paren_depth_across_chunks() -> None:
    p = CueStreamParser("r", "m")
    outs = p.feed("你好（跨")
    outs += p.feed("chunk！）后续。[[cue:wink]]末句")
    cues = _cues(outs)
    assert [c.sentence_index for c in cues] == [2]


def test_consecutive_terminators_count_once() -> None:
    p = CueStreamParser("r", "m")
    outs = p.feed("好！！[[cue:happy]]真的吗？！")
    assert _cues(outs)[0].sentence_index == 2  # ！！折叠为一个边界


# ---------------------------------------------------------------------------
# LLMAgentService cue 路径集成
# ---------------------------------------------------------------------------


def _plain_agent(calls: list[list[Any]]) -> LLMAgentService:
    """cue 路径关闭（默认构造，与 test_llm_agent 同构）。"""
    return LLMAgentService(make_test_adapter(ScriptedChatModel(calls=calls)))


def _cue_agent(
    calls: list[list[Any]],
    skin_provider: Any | None = None,
) -> tuple[LLMAgentService, ScriptedChatModel]:
    model = ScriptedChatModel(calls=calls)
    agent = LLMAgentService(
        make_test_adapter(model),
        cue_enabled=True,
        skin_provider=skin_provider,
    )
    return agent, model


def _system_text(model: ScriptedChatModel) -> str:
    """首轮收到的 system 消息全文（G2 提示词断言用）。"""
    from langchain_core.messages import SystemMessage

    for msg in model.received[0]:
        if isinstance(msg, SystemMessage):
            return str(msg.content)
    return ""


def _ctx() -> AgentContext:
    return AgentContext(run_id="r-1", session_id="s-1", text="你好")


@pytest.mark.asyncio
async def test_run_emits_character_cue_and_clean_full_text() -> None:
    """集成：标记解析 → character.cue 事件；text.end 落盘文本为清洗后全文。"""
    agent, _model = _cue_agent(
        [[AIMessageChunk(content="别担心。"), AIMessageChunk(content="[[cue:comfort]]我来帮你。")]]
    )
    events = [(t, p) async for t, p in agent.run(_ctx())]

    cue_events = [(t, p) for t, p in events if t == "character.cue"]
    assert len(cue_events) == 1
    cue = cue_events[0][1]
    assert cue.run_id == "r-1"
    assert cue.channels.body.action_id == "comfort"
    # cue 位于 text.start 之后、text.end 之前（同一 run 流内）
    order = [t for t, _ in events]
    assert order.index("character.cue") > order.index("text.start")
    assert order.index("character.cue") < order.index("text.end")

    text_end = next(p for t, p in events if t == "text.end")
    assert text_end.full_text == "别担心。我来帮你。"  # 零泄漏

    deltas = "".join(p.delta for t, p in events if t == "text.delta")
    assert "[[cue" not in deltas


@pytest.mark.asyncio
async def test_cue_run_skips_post_run_emotion() -> None:
    """互斥：发过 reply cue 的 run 不再暂存回复 → post_run_events 不发 emotion。"""
    agent, _model = _cue_agent([[AIMessageChunk(content="很遗憾。[[cue:sad]]")]])
    async for _ in agent.run(_ctx()):
        pass

    assert await agent.post_run_events(_ctx()) == []


@pytest.mark.asyncio
async def test_cue_path_off_emits_no_cue_events() -> None:
    """cue 路径关闭（默认）：无 character.cue 事件、文本原样（M-B 行为零回归）。"""
    agent = _plain_agent([[AIMessageChunk(content="纯文本回复")]])
    events = [(t, p) async for t, p in agent.run(_ctx())]
    assert not any(t == "character.cue" for t, _ in events)
    assert next(p for t, p in events if t == "text.end").full_text == "纯文本回复"


# ---------------------------------------------------------------------------
# G2：cue 提示词按皮肤能力注入
# ---------------------------------------------------------------------------


def _skin_with_actions(*action_ids: str, name: str = "团子·Hiyori") -> SkinManifest:
    return SkinManifest.model_validate(
        {
            "id": "test-skin",
            "name": name,
            "resourceType": "live2d",
            "modelFile": "m.model3.json",
            "actions": [
                {
                    "id": aid,
                    "channels": ["body"],
                    "agentSelectable": True,
                    "live2d": {"motionGroups": ["Tap"]},
                }
                for aid in action_ids
            ],
        }
    )


def test_cue_prompt_static_when_no_skin() -> None:
    """skin=None：静态全词表（零回归）。"""
    section = cue_prompt_section()
    assert "当前装扮" not in section
    assert "[[cue:id]]" in section
    for aid in ("wink", "nod", "pout"):
        assert aid in section
    assert "不要发明清单外" not in section


def test_cue_prompt_dynamic_injection_filters_to_skin() -> None:
    """有皮肤清单：只教皮肤可演动作（label(id) 对照 + 示例指示词 + 收窄声明）。"""
    section = cue_prompt_section(_skin_with_actions("wink", "nod"))
    assert "当前装扮「团子·Hiyori」" in section
    assert "眨眨眼(wink)" in section
    assert "点头(nod)" in section
    assert "pout" not in section  # 未声明 → 不教
    assert "眨了眨眼" in section  # 示例指示词跟随可演动作
    assert "不要发明清单外" in section


def test_cue_prompt_dynamic_excludes_unselectable() -> None:
    """agentSelectable=false 不进清单（idle_neutral 由词表约束永不可选）。"""
    manifest = SkinManifest.model_validate(
        {
            "id": "test-skin",
            "name": "s",
            "resourceType": "live2d",
            "modelFile": "m.model3.json",
            "actions": [
                {
                    "id": "wink",
                    "channels": ["body"],
                    "agentSelectable": True,
                    "live2d": {"motionGroups": ["Wink"]},
                },
                {
                    "id": "nod",
                    "channels": ["body"],
                    "agentSelectable": False,
                    "live2d": {"motionGroups": ["Tap"]},
                },
            ],
        }
    )
    section = cue_prompt_section(manifest)
    assert "wink" in section
    assert "nod" not in section


def test_cue_prompt_dynamic_falls_back_when_no_semantic_actions() -> None:
    """清单只有自定义 id（∩词表为空）→ 回落静态全词表（不教空集）。"""
    section = cue_prompt_section(_skin_with_actions("custom_trick"))
    assert "当前装扮" not in section
    assert "pout" in section


def test_action_example_words() -> None:
    from mochi_server.agent.stage_directions import action_example_words

    assert action_example_words("wink")  # wink 有示例词（长词优先）
    assert action_example_words("wink") == ["眨了眨眼", "眨眨眼", "眨了眨"]
    assert action_example_words("非词表动作") == []


@pytest.mark.asyncio
async def test_cue_agent_injects_skin_capabilities() -> None:
    """G2：skin_provider 返回清单 → system prompt 只教该皮肤可演动作。"""
    calls = [[AIMessageChunk(content="好。")]]
    model = ScriptedChatModel(calls=calls)
    agent, model = _cue_agent(calls, skin_provider=lambda: _skin_with_actions("wink"))
    async for _ in agent.run(_ctx()):
        pass
    system = _system_text(model)
    assert "当前装扮「团子·Hiyori」" in system
    assert "眨眨眼(wink)" in system
    assert "pout" not in system


@pytest.mark.asyncio
async def test_cue_agent_skin_provider_error_falls_back() -> None:
    """G2：provider 抛异常 → 回落静态全词表，回合不失败。"""
    calls = [[AIMessageChunk(content="好。")]]
    model = ScriptedChatModel(calls=calls)

    def _boom() -> Any:
        raise RuntimeError("registry down")

    agent, model = _cue_agent(calls, skin_provider=_boom)
    events = [(t, p) async for t, p in agent.run(_ctx())]
    assert any(t == "text.end" for t, _ in events)  # 回合正常完成
    system = _system_text(model)
    assert "当前装扮" not in system
    assert "pout" in system  # 静态全词表


@pytest.mark.asyncio
async def test_cue_agent_without_provider_keeps_static_prompt() -> None:
    """G2：未注入 provider（零回归路径）→ 静态全词表。"""
    calls = [[AIMessageChunk(content="好。")]]
    model = ScriptedChatModel(calls=calls)
    agent, model = _cue_agent(calls)
    async for _ in agent.run(_ctx()):
        pass
    system = _system_text(model)
    assert "当前装扮" not in system
    assert "[[cue:id]]" in system
