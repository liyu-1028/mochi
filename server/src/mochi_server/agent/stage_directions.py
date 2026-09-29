"""StageDirectionScanner —— 中文舞台指示解析（M-F，借鉴 Open-LLM-VTuber）。

调研依据（docs/internal/research/desktop-companion-behavior-and-action-research.md
§3 AIRI + 2026-09 补充调研 Open-LLM-VTuber）：
- OLLVT ``think_tag_prompt``：模型把动作写成括号舞台指示，气泡展示但 TTS 跳过；
- OLLVT ``tts_preprocessor.tts_filter``：TTS 前剥离括号内容（display 保留）；
- Mochi 的 M-C 基建（[[cue:id]] 白名单标记）等价于 AIRI 内联标记方案。
本模块补上缺口：人格自然写出的 ``（眨眨眼）（点点头）`` 式舞台指示 →
结构化 character.cue，让角色**边说边做**。

设计约束（与 cue_extractor 同一套红线）：
- **文本零改动**：舞台指示保留在气泡里（人格魅力的一部分），只额外触发动作
  cue——与 OLLVT「TTS 过滤、展示保留」同构；TTS 剥离由前端 useTTS 负责；
- **白名单铁律**：body 只映射 SEMANTIC_ACTIONS 词表内动作，face 只映射
  EMOTIONS 词表内情绪；映射表是封闭字典，未命中的指示静默忽略；
- **分句口径与 TTS 一致**：sentenceIndex 按「剥离舞台指示后的文本」计数
  （cue_extractor 的分句计数已同步跳过括号内终止符，两端口径一致）；
- 确定性：无随机源、无定时器；逐 delta feed、流末 flush，跨 chunk 持有
  未闭合的 ``（`` 缓存；单回复上限复用 MAX_CUES_PER_REPLY。

生命周期与一次回复正文流绑定（与 CueStreamParser 平行运行，吃同一清洗流）。
"""

from __future__ import annotations

import logging
import re
import uuid

from ..events import (
    CUE_INTERRUPT_POLICY_VALUES,
    CharacterCueData,
    CueBodyChannel,
    CueChannels,
    CueFaceChannel,
    Emotion,
)
from .cue_extractor import (
    MAX_CUES_PER_REPLY,
    REPLY_CUE_INTENSITY,
    REPLY_CUE_PRIORITY,
    REPLY_CUE_TTL_MS,
)

logger = logging.getLogger(__name__)

#: 舞台指示映射表：关键词 → (通道, 白名单 id)。
#: 封闭字典——「能做出来的动作」才收录；模型写出做不出的描写
#: （如「掏出皱巴巴的申请表」）静默忽略，绝不硬猜资源。
#: 同通道多词命中取最长优先的第一个；一段指示最多产 1 body + 1 face。
DIRECTION_KEYWORDS: dict[str, tuple[str, str]] = {
    # -- body：语义动作（SEMANTIC_ACTIONS 白名单内）--
    "眨了眨眼": ("body", "wink"),
    "眨眨眼": ("body", "wink"),
    "眨了眨": ("body", "wink"),
    "眨眼": ("body", "wink"),
    "挥挥手": ("body", "wave"),
    "挥了挥手": ("body", "wave"),
    "挥手": ("body", "wave"),
    "点了点头": ("body", "nod"),
    "点点头": ("body", "nod"),
    "点头": ("body", "nod"),
    "摇了摇头": ("body", "shake_head"),
    "摇头": ("body", "shake_head"),
    "鼓掌": ("body", "celebrate"),
    "欢呼": ("body", "celebrate"),
    "庆祝": ("body", "celebrate"),
    "拍拍": ("body", "comfort"),
    "摸了摸": ("body", "comfort"),
    "摸摸": ("body", "comfort"),
    "安慰": ("body", "comfort"),
    "吓了一跳": ("body", "surprised"),
    "倒吸一口": ("body", "surprised"),
    "东张西望": ("body", "look_around"),
    "左顾右盼": ("body", "look_around"),
    "环顾": ("body", "look_around"),
    "看了看四周": ("body", "look_around"),
    "沉思": ("body", "think"),
    "思考": ("body", "think"),
    "想了想": ("body", "think"),
    "琢磨": ("body", "think"),
    "伸懒腰": ("body", "stretch"),
    "打哈欠": ("body", "doze"),
    "打呵欠": ("body", "doze"),
    "打盹": ("body", "doze"),
    "犯困": ("body", "doze"),
    "瞌睡": ("body", "doze"),
    "犯困点头": ("body", "doze"),
    "竖起耳朵": ("body", "listen"),
    "侧耳": ("body", "listen"),
    # -- body：G1（L1 包络扩容）--
    "嘟起嘴": ("body", "pout"),
    "嘟嘴": ("body", "pout"),
    "啾嘴": ("body", "pout"),
    "撒嘴": ("body", "pout"),
    "大笑": ("body", "laugh"),
    "哈哈大笑": ("body", "laugh"),
    "咯咯笑": ("body", "laugh"),
    "捧腹": ("body", "laugh"),
    "笑弯了腰": ("body", "laugh"),
    "扭捏": ("body", "shy_shake"),
    "忸怩": ("body", "shy_shake"),
    "局促": ("body", "shy_shake"),
    "羞涩地摇头": ("body", "shy_shake"),
    "警觉": ("body", "alert"),
    "警惕": ("body", "alert"),
    "猛地抬头": ("body", "alert"),
    "精神一振": ("body", "alert"),
    "打起精神": ("body", "alert"),
    # -- body：G5（2b 资产解锁）——仅当皮肤扩展包提供对应 motion3.json 才可演
    "跳跃": ("body", "jump"),
    "跳了一下": ("body", "jump"),
    "蹦跳": ("body", "jump"),
    "开心地跳": ("body", "jump"),
    "转了个圈": ("body", "spin"),
    "转圈": ("body", "spin"),
    "旋转": ("body", "spin"),
    "鞠了个躬": ("body", "bow"),
    "鞠躬": ("body", "bow"),
    "弯腰行礼": ("body", "bow"),
    "欠身": ("body", "bow"),
    # -- body：批次 3（I1，L1 包络）--
    "跳个舞": ("body", "dance"),
    "跳舞": ("body", "dance"),
    "手舞足蹈": ("body", "dance"),
    "扭起来": ("body", "dance"),
    "比了个心": ("body", "finger_heart"),
    "比心": ("body", "finger_heart"),
    "比颗心": ("body", "finger_heart"),
    "送个飞吻": ("body", "blow_kiss"),
    "飞吻": ("body", "blow_kiss"),
    "么么哒": ("body", "blow_kiss"),
    "满脸问号": ("body", "question"),
    "一头雾水": ("body", "question"),
    "冒出问号": ("body", "question"),
    "不解地歪头": ("body", "question"),
    "敲键盘": ("body", "type"),
    "打字": ("body", "type"),
    # -- face：情绪（EMOTIONS 词表内）--
    "微笑": ("face", "happy"),
    "笑了笑": ("face", "happy"),
    "嘻嘻": ("face", "happy"),
    "嘿嘿": ("face", "happy"),
    "开心": ("face", "happy"),
    "耷拉": ("face", "sad"),
    "垂头": ("face", "sad"),
    "委屈": ("face", "sad"),
    "难过": ("face", "sad"),
    "沮丧": ("face", "sad"),
    "脸红": ("face", "embarrassed"),
    "红着脸": ("face", "embarrassed"),
    "害羞": ("face", "embarrassed"),
    "不好意思": ("face", "embarrassed"),
    "困惑": ("face", "confused"),
    "疑惑": ("face", "confused"),
    "歪头": ("face", "confused"),
    "纳闷": ("face", "confused"),
    "惊讶": ("face", "surprised"),
    "震惊": ("face", "surprised"),
    "瞪大": ("face", "surprised"),
    "吃惊": ("face", "surprised"),
    "生气": ("face", "angry"),
    "气鼓鼓": ("face", "angry"),
    "恼火": ("face", "angry"),
}

#: 同通道多词命中时长词优先（「眨了眨眼」先于「眨眼」）
_KEYWORDS_BY_LENGTH = sorted(DIRECTION_KEYWORDS, key=len, reverse=True)

#: 动作 id → 示例指示词（G2）：按长词优先预排序，供提示词能力注入选取
_KEYWORDS_BY_ACTION: dict[str, list[str]] = {}
for _kw, (_ch, _aid) in sorted(
    DIRECTION_KEYWORDS.items(), key=lambda item: len(item[0]), reverse=True
):
    if _ch == "body":
        _KEYWORDS_BY_ACTION.setdefault(_aid, []).append(_kw)


#: 全角括号（人格舞台指示的书写惯例；半角括号可能是代码/数学，不碰）
_OPEN, _CLOSE = "（", "）"

_FACE_EMOTIONS = frozenset(e.value for e in Emotion)


def map_direction(text: str) -> tuple[str, str] | None:
    """一段指示内容 → (通道, id)；未命中返回 None（静默忽略，可观测于日志）。"""
    for kw in _KEYWORDS_BY_LENGTH:
        if kw in text:
            return DIRECTION_KEYWORDS[kw]
    return None


def action_example_words(action_id: str, limit: int = 3) -> list[str]:
    """动作 id → 示例舞台指示词（长词优先，G2 提示词能力注入用）。

    仅 body 通道语义词表内动作有示例；limit 截断避免提示词膨胀。
    """
    return _KEYWORDS_BY_ACTION.get(action_id, [])[:limit]


class StageDirectionScanner:
    """流式舞台指示扫描器。逐 delta feed；流末 flush。

    与 CueStreamParser 平行运行：llm_agent 把**同一清洗文本增量**喂给两者。
    本扫描器只产 cue、不改文本（气泡保留指示原文）。
    """

    def __init__(self, run_id: str, message_id: str, *, source: str = "reply") -> None:
        self._run_id = run_id
        self._message_id = message_id
        self._source = source
        self._hold = ""  # 疑似未闭合指示（自最后一个 _OPEN 起）
        self._sentences_done = 0  # 剥离口径下已完成边界数
        self._pending_tail = ""  # 末尾终止符串（跨增量折叠）
        self._paren_depth = 0  # 跨增量括号深度（正文层）
        self._emitted_any_text = False
        self._cue_count = 0
        self.dropped: dict[str, int] = {}

    # -- 公开接口 -----------------------------------------------------------

    def feed(self, delta: str) -> list[CharacterCueData]:
        """喂入一个清洗文本增量，返回该增量内闭合指示产出的 cue 序列（保序）。"""
        cues: list[CharacterCueData] = []
        buf = self._hold + delta
        self._hold = ""
        pos = 0
        while pos < len(buf):
            open_at = buf.find(_OPEN, pos)
            if open_at < 0:
                cues.extend(self._scan_visible(buf[pos:]))
                break
            cues.extend(self._scan_visible(buf[pos:open_at]))
            close_at = buf.find(_CLOSE, open_at + 1)
            if close_at < 0:
                # 未闭合：挂起等下一增量（嵌套括号按内容中的第一个 _CLOSE 收口）
                self._hold = buf[open_at:]
                break
            cues.extend(self._take_direction(buf[open_at + 1 : close_at]))
            pos = close_at + 1
        return cues

    def flush(self) -> list[CharacterCueData]:
        """流末收口：未闭合的残段（截断指示）丢弃，不产 cue。"""
        if self._hold:
            self._count("unclosed_dropped")
            self._hold = ""
        return []

    def _scan_visible(self, text: str) -> list[CharacterCueData]:
        """推进「剥离口径」分句计数（与 cue_extractor 括号感知口径一致）。"""
        if not text:
            return []
        merged = self._pending_tail + text
        if not self._emitted_any_text:
            merged = merged.lstrip("。！？!?；;\n")
            if not merged:
                self._pending_tail = ""
                return []
            self._emitted_any_text = True
        # 末尾连续终止符暂不确认完成（下一增量可能折叠/续正文）
        i = len(merged)
        while i > 0 and merged[i - 1] in "。！？!?；;\n":
            i -= 1
        body, tail = merged[:i], merged[i:]
        count = 0
        depth = self._paren_depth
        prev_boundary = False
        for ch in body:
            if ch == _OPEN:
                depth += 1
                prev_boundary = False
            elif ch == _CLOSE:
                depth = max(0, depth - 1)
                prev_boundary = False
            elif ch in "。！？!?；;\n":
                if depth == 0 and not prev_boundary:
                    count += 1
                prev_boundary = True
            else:
                prev_boundary = False
        self._sentences_done += count
        self._paren_depth = depth
        self._pending_tail = tail
        return []

    def _take_direction(self, content: str) -> list[CharacterCueData]:
        """闭合指示 → 白名单映射 → 0/1 个 cue（face+body 可并载）。"""
        # 指示前的句末终止符此时已确认完成（指示即位于下一句）
        if self._pending_tail:
            self._sentences_done += 1
            self._pending_tail = ""
        hit = map_direction(content)
        if hit is None:
            self._count("unmapped")
            return []
        channel, action_id = hit
        if channel == "face" and action_id not in _FACE_EMOTIONS:  # 双保险
            self._count("unknown_emotion")
            return []
        self._cue_count += 1
        if self._cue_count > MAX_CUES_PER_REPLY:
            self._count("cap_reached")
            return []
        if not self._emitted_any_text:
            sync, sentence_index = "speech_start", 1
        else:
            sync, sentence_index = "sentence_boundary", self._sentences_done + 1
        channels = (
            CueChannels(face=CueFaceChannel(emotion=action_id, intensity=REPLY_CUE_INTENSITY))
            if channel == "face"
            else CueChannels(body=CueBodyChannel(action_id=action_id))
        )
        logger.info("舞台指示 → cue：%s（%s:%s）", content[:24], channel, action_id)
        return [
            CharacterCueData(
                cue_id=f"d-{uuid.uuid4().hex[:12]}",
                run_id=self._run_id,
                message_id=self._message_id,
                source=self._source,
                channels=channels,
                sync=sync,
                sentence_index=sentence_index,
                priority=REPLY_CUE_PRIORITY,
                interrupt_policy=CUE_INTERRUPT_POLICY_VALUES[0],
                ttl_ms=REPLY_CUE_TTL_MS,
            )
        ]

    def _count(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1


#: 剥离口径的 TTS 清洗正则：全角成对括号段 + 流末未闭合残段（与人格书写惯例
#: 对齐；半角括号可能是代码/数学表达式，不碰）。
_DIRECTION_PAIR = re.compile(r"（[^（）]*）")
_DIRECTION_OPEN_TAIL = re.compile(r"（[^（）]*$")


def strip_stage_directions(text: str) -> str:
    """TTS 前剥离舞台指示（OLLVT tts_filter 的括号过滤，全角口径）。

    气泡文本不走此函数——指示保留展示。剥离（...）成对段与流末未闭合残段，
    多次调用幂等。
    """
    return _DIRECTION_OPEN_TAIL.sub("", _DIRECTION_PAIR.sub("", text))
