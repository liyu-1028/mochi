"""StageDirectionScanner（M-F）单测：中文舞台指示 → character.cue。

验收锚点：
- 白名单封闭字典：能做的动作才映射；做不出的描写静默忽略（unmapped 计数）；
- 文本零改动职责：本扫描器不产文本（气泡保留由 llm_agent 保证）；
- sentenceIndex 与 TTS 剥离口径一致（指示内终止符不计入分句）；
- 跨 chunk：未闭合的（ 挂起等待；流末未闭合丢弃（unclosed_dropped）；
- 上限：单回复 cue 数复用 MAX_CUES_PER_REPLY；
- strip_stage_directions：成对段与流末残段均剥离，幂等。
"""

from __future__ import annotations

from mochi_server.agent.cue_extractor import MAX_CUES_PER_REPLY
from mochi_server.agent.stage_directions import (
    StageDirectionScanner,
    map_direction,
    strip_stage_directions,
)

# ---------------------------------------------------------------------------
# 映射表
# ---------------------------------------------------------------------------


def test_map_direction_body_whitelist() -> None:
    assert map_direction("悄悄眨眨眼") == ("body", "wink")
    assert map_direction("轻轻点头") == ("body", "nod")
    assert map_direction("把耳朵耷拉下来") == ("face", "sad")
    assert map_direction("不好意思地脸红") == ("face", "embarrassed")


def test_map_direction_longest_first() -> None:
    # 「眨了眨眼」不得被「眨眼」提前截胡
    assert map_direction("眨了眨眼") == ("body", "wink")
    assert map_direction("点了点头") == ("body", "nod")


def test_map_direction_g1_envelope_actions() -> None:
    """G1（L1 包络扩容）：嘟嘴/大笑/扭捏/警觉/犯困点头。"""
    assert map_direction("嘟起嘴") == ("body", "pout")
    assert map_direction("不满地嘟嘴") == ("body", "pout")
    assert map_direction("哈哈大笑") == ("body", "laugh")
    assert map_direction("笑弯了腰") == ("body", "laugh")
    assert map_direction("害羞地扭捏") == ("body", "shy_shake")
    assert map_direction("突然警觉") == ("body", "alert")
    assert map_direction("打起精神") == ("body", "alert")
    assert map_direction("听得犯困点头") == ("body", "doze")


def test_map_direction_unmapped_returns_none() -> None:
    # 做不出的舞台描写 → None（不硬猜资源）
    assert map_direction("慢动作掏出一张皱巴巴的重修申请表") is None
    assert map_direction("把小爪子藏到背后") is None


# ---------------------------------------------------------------------------
# 扫描器
# ---------------------------------------------------------------------------


def _feed_all(scanner: StageDirectionScanner, text: str, chunk: int = 4):
    cues = []
    for i in range(0, len(text), chunk):
        cues.extend(scanner.feed(text[i : i + chunk]))
    cues.extend(scanner.flush())
    return cues


def test_direction_becomes_body_cue() -> None:
    s = StageDirectionScanner("r", "m")
    cues = _feed_all(s, "那来个笑话（眨眨眼）为什么AI从不跟咖啡吵架？")
    assert len(cues) == 1
    assert cues[0].channels.body is not None
    assert cues[0].channels.body.action_id == "wink"
    assert cues[0].channels.face is None
    assert cues[0].source == "reply"
    assert cues[0].priority == 45


def test_direction_face_cue() -> None:
    s = StageDirectionScanner("r", "m")
    cues = _feed_all(s, "（轻轻把耳朵耷拉下来）但——等等！")
    assert len(cues) == 1
    assert cues[0].channels.face is not None
    assert cues[0].channels.face.emotion == "sad"


def test_unmapped_direction_dropped_with_counter() -> None:
    s = StageDirectionScanner("r", "m")
    cues = _feed_all(s, "（慢动作掏出申请表）你好呀。")
    assert cues == []
    assert s.dropped.get("unmapped") == 1


def test_sentence_index_matches_tts_stripped_text() -> None:
    # 指示出现在第 2 句开头 → sentence_index=2（指示自身不产生分句）
    s = StageDirectionScanner("r", "m")
    cues = _feed_all(s, "第一句。（眨眨眼）第二句！（点点头）第三句")
    assert [c.sentence_index for c in cues] == [2, 3]


def test_direction_with_terminator_inside_does_not_split() -> None:
    # 指示内含终止符（（重修申请表！））不推进分句——TTS 剥离后该终止符不存在
    s = StageDirectionScanner("r", "m")
    cues = _feed_all(s, "哎呀（重修申请表！）不好。之后的话")
    assert len(cues) == 0
    cues2 = _feed_all(s, "（眨眨眼）下一句")
    assert len(cues2) == 1
    # 「之后的话」是第 2 句（「不好。」才是第 1 句边界）
    assert cues2[0].sentence_index == 2


def test_unclosed_direction_held_across_chunks() -> None:
    s = StageDirectionScanner("r", "m")
    cues = []
    cues.extend(s.feed("你好（眨"))
    assert cues == []  # 未闭合：挂起
    cues.extend(s.feed("眨眼）！欢迎。"))
    assert len(cues) == 1
    assert cues[0].channels.body.action_id == "wink"


def test_unclosed_at_flush_dropped() -> None:
    s = StageDirectionScanner("r", "m")
    cues = _feed_all(s, "你好（悄悄把小爪子藏到背后")
    assert cues == []
    assert s.dropped.get("unclosed_dropped") == 1


def test_direction_at_stream_start_is_speech_start() -> None:
    s = StageDirectionScanner("r", "m")
    cues = s.feed("（挥手）你好！")
    assert len(cues) == 1
    assert cues[0].sync == "speech_start"
    assert cues[0].sentence_index == 1


def test_cap_on_directions() -> None:
    s = StageDirectionScanner("r", "m")
    text = "（点头）" * (MAX_CUES_PER_REPLY + 2)
    cues = _feed_all(s, text)
    assert len(cues) == MAX_CUES_PER_REPLY
    assert s.dropped.get("cap_reached") == MAX_CUES_PER_REPLY + 2 - MAX_CUES_PER_REPLY


# ---------------------------------------------------------------------------
# TTS 剥离
# ---------------------------------------------------------------------------


def test_strip_stage_directions_pairs() -> None:
    assert strip_stage_directions("你好（眨眨眼）世界！") == "你好世界！"
    assert strip_stage_directions("（挥手）开局（点头）收尾") == "开局收尾"


def test_strip_stage_directions_unclosed_tail() -> None:
    assert strip_stage_directions("你好（悄悄") == "你好"


def test_strip_stage_directions_idempotent() -> None:
    once = strip_stage_directions("好（笑）！）奇怪（（套）")
    assert strip_stage_directions(once) == once


def test_strip_keeps_half_width_parens() -> None:
    # 半角括号（代码/数学惯例）不剥离
    assert strip_stage_directions("f(x) = x + 1") == "f(x) = x + 1"
