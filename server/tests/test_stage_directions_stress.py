"""StageDirectionScanner 严厉流式压力测试与极限边界测试。"""

from __future__ import annotations

from mochi_server.agent.cue_extractor import MAX_CUES_PER_REPLY
from mochi_server.agent.stage_directions import (
    StageDirectionScanner,
    strip_stage_directions,
)


def _feed_char_by_char(scanner: StageDirectionScanner, text: str):
    """最严厉的流式模拟：单字符逐 delta 喂入。"""
    cues = []
    for ch in text:
        cues.extend(scanner.feed(ch))
    cues.extend(scanner.flush())
    return cues


def test_char_by_char_direction_at_start() -> None:
    """极限流式：开头单字流式喂入舞台指示，产出 speech_start 且 sentence_index=1。"""
    s = StageDirectionScanner("r", "m")
    cues = _feed_char_by_char(s, "（眨眨眼）早上好呀！")
    assert len(cues) == 1
    assert cues[0].channels.body is not None
    assert cues[0].channels.body.action_id == "wink"
    assert cues[0].sync == "speech_start"
    assert cues[0].sentence_index == 1


def test_char_by_char_multi_sentence_sequence() -> None:
    """极限流式：单字符逐字切分下，分句计数与句首指示完美对齐。"""
    s = StageDirectionScanner("r", "m")
    text = "第一句。（眨眨眼）第二句！？？（点点头）第三句；（微笑）第四句。"
    cues = _feed_char_by_char(s, text)
    assert len(cues) == 3
    # 动作 1: wink 在第 2 句
    assert cues[0].channels.body.action_id == "wink"
    assert cues[0].sentence_index == 2
    # 动作 2: nod 在第 3 句
    assert cues[1].channels.body.action_id == "nod"
    assert cues[1].sentence_index == 3
    # 动作 3: happy 在第 4 句
    assert cues[2].channels.face.emotion == "happy"
    assert cues[2].sentence_index == 4


def test_consecutive_stage_directions() -> None:
    """连续多个括号指示：例如（眨眨眼）（微笑）在句首。"""
    s = StageDirectionScanner("r", "m")
    cues = _feed_char_by_char(s, "（眨眨眼）（微笑）今天天气真好。")
    assert len(cues) == 2
    assert cues[0].channels.body.action_id == "wink"
    assert cues[0].sync == "speech_start"
    assert cues[1].channels.face.emotion == "happy"
    assert cues[1].sync == "speech_start"


def test_stage_direction_with_whitespace_and_newlines() -> None:
    """指示内包含换行符与空格：正常识别。"""
    s = StageDirectionScanner("r", "m")
    cues = _feed_char_by_char(s, "（  眨眨眼  \n）开始")
    assert len(cues) == 1
    assert cues[0].channels.body.action_id == "wink"


def test_empty_parentheses_dropped_gracefully() -> None:
    """空括号不报错，记录 unmapped。"""
    s = StageDirectionScanner("r", "m")
    cues = _feed_char_by_char(s, "你好（）世界")
    assert cues == []
    assert s.dropped.get("unmapped") == 1


def test_leading_punctuation_does_not_shift_sentence_index() -> None:
    """文本以连续换行与标点开头，首个指示的分句编号仍为 1。"""
    s = StageDirectionScanner("r", "m")
    cues = _feed_char_by_char(s, "\n\n！？。。（点头）你好！")
    assert len(cues) == 1
    assert cues[0].sync == "speech_start"
    assert cues[0].sentence_index == 1


def test_high_volume_stress_cues_cap() -> None:
    """高频压力测试：超长文本 + 50 个指示，严格遵守上限且无内存泄漏。"""
    s = StageDirectionScanner("r", "m")
    # 构造 50 句，每句带指示
    chunks = [f"第{i}句内容。（点头）" for i in range(50)]
    full_text = "".join(chunks)
    cues = _feed_char_by_char(s, full_text)
    assert len(cues) == MAX_CUES_PER_REPLY
    assert s.dropped.get("cap_reached") == 50 - MAX_CUES_PER_REPLY


def test_half_width_parentheses_completely_ignored() -> None:
    """半角括号（代码/数学表达式）完全忽略，不提取任何 cue。"""
    s = StageDirectionScanner("r", "m")
    cues = _feed_char_by_char(s, "这里有一个函数 call(wink) 和数学 (x + y)。")
    assert cues == []
    assert len(s.dropped) == 0


def test_strip_stage_directions_stress_cases() -> None:
    """TTS 剥离极端情况。"""
    # 纯指示
    assert strip_stage_directions("（眨眨眼）（微笑）") == ""
    # 指示内有标点与代码符号
    assert strip_stage_directions("前（眨眨眼，微笑！`code`）后") == "前后"
    # 流末未闭合截断
    assert strip_stage_directions("一二三（未闭合残段") == "一二三"
    # 保留半角括号
    assert strip_stage_directions("x = (a + b) * （点头） c") == "x = (a + b) *  c"
