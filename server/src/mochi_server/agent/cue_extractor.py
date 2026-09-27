"""CueStreamParser —— 回复流中的表演节拍标记解析（M-C，调研报告 §8.3）。

职责：模型在回复文本中内联的 `[[cue:id]]` 标记 → 结构化 character.cue 事件，
**标记绝不进入可见文本**（气泡 / TTS / 落盘用的 full_text 均为清洗后文本）。

生成路径决策（rollout plan §8 决策点 2）：结构化输出优先——但流式 ReAct 图内
provider 结构化输出与工具绑定/流式不兼容，故正文路径采用内联标记作为适配器
内部实现（协议仍是正式 character.cue 事件，标记仅存在于服务端内存，解析后
立即剥离——调研报告 §4.2 的建议形态）。

零泄漏规则（验收 P0）：
- 完整合法标记 → 提取为 cue，不产文本；
- `[[` + 空白 + "cue" 前缀的**畸形/半畸形**标记（`[[cue:`、`[[cue:未知]]`、
  `[[cue happy]]`、跨 chunk 截断、流末未闭合等）→ 整段丢弃并计数，绝不外泄；
- 与标记无关的 `[[`（如 markdown 脚注语法）→ 原样作为文本输出（流末 flush）。

白名单铁律（协议 §11）：body 只接受 agentSelectable 语义动作 id；
face 只接受 EMOTIONS 词表；未知 id 丢弃 + 计数（日志可观测）。

分句规则（双端一致的规范约定，前端 cueScheduler 同规则实现对齐）：
终止符 `。！？!?；;` 与换行，连续终止符折叠为一个边界；
sentenceIndex 为标记位置前已完成边界数 + 1（1-based）。
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from ..events import (
    CUE_INTERRUPT_POLICY_VALUES,
    SEMANTIC_ACTIONS,
    CharacterCueData,
    CueBodyChannel,
    CueChannels,
    CueFaceChannel,
    Emotion,
)

logger = logging.getLogger(__name__)

#: 终点动作不可被模型选择（全链路兜底，M-A 约束）
_AGENT_SELECTABLE = frozenset(SEMANTIC_ACTIONS) - {"idle_neutral"}
_FACE_EMOTIONS = frozenset(e.value for e in Emotion)

#: 单次回复的 cue 上限（防刷屏；超出丢弃计数）
MAX_CUES_PER_REPLY = 8

#: reply 来源 cue 的固定参数（服务端定值，模型不可指定）
REPLY_CUE_PRIORITY = 45
REPLY_CUE_TTL_MS = 15_000
REPLY_CUE_INTENSITY = 0.75

#: 分句终止符（规范约定；连续出现折叠为一个边界）
_SENTENCE_TERMINATORS = frozenset("。！？!?；;\n")

#: `[[` + 空白 + "cue"（大小写不敏感）→ 判定为控制标记尝试（畸形也丢弃）
_TAG_ATTEMPT = re.compile(r"\[\[\s*cue", re.IGNORECASE)
#: 前缀判定基准字面量（判定时忽略空白、大小写不敏感）
_ATTEMPT_LITERAL = "[[cue"
#: 完整标记：[[cue:id]]（id 限 [a-z_]，容忍两侧空白；大小写敏感——词表全小写）
_TAG_COMPLETE = re.compile(r"\[\[\s*cue\s*:\s*([a-z_]{1,32})\s*\]\]")
#: 流末残骸的最小标记语法前缀（[[cue:id——用于只丢残骸、保住其后正文）
_MALFORMED_PREFIX = re.compile(r"\[\[\s*cue\s*:\s*[A-Za-z_]*")

#: 白名单丢弃原因（日志计数键）
_DROP_UNKNOWN = "unknown_action"
_DROP_TERMINAL = "terminal_action"
_DROP_CAP = "cap_reached"
_DROP_MALFORMED = "malformed_tag"


@dataclass
class ParserOutput:
    """feed/flush 的产出：清洗文本增量或一个待发射 cue。"""

    kind: str  # "text" | "cue"
    text: str = ""
    cue: CharacterCueData | None = None


class CueStreamParser:
    """流式标记解析器。逐 delta feed；流末 flush。

    生命周期与一次回复正文流绑定；跨 chunk 持有可能是标记前缀的尾部缓存，
    决策后要么提取、要么放行/丢弃。非线程安全（单事件循环内使用）。
    """

    def __init__(self, run_id: str, message_id: str) -> None:
        self._run_id = run_id
        self._message_id = message_id
        self._hold = ""  # 疑似标记前缀缓存（尚未决策）
        self._sentences_done = 0  # 已完成分句边界数
        self._pending_tail = ""  # 上一段文本末尾的终止符串（跨增量折叠，未确认完成）
        self._emitted_any_text = False
        self._cue_count = 0
        # 丢弃计数（验收：越权/未知丢弃可在日志观测）
        self.dropped: dict[str, int] = {}

    # -- 公开接口 -----------------------------------------------------------

    def feed(self, delta: str) -> list[ParserOutput]:
        """喂入一个正文增量，返回 [清洗文本 / cue] 序列（保序）。"""
        out: list[ParserOutput] = []
        buf = self._hold + delta
        self._hold = ""
        pos = 0
        while pos < len(buf):
            start = buf.find("[[", pos)
            if start < 0:
                out.extend(self._emit_text(buf[pos:]))
                break
            # 标记前的普通文本先放行（并计入分句）
            out.extend(self._emit_text(buf[pos:start]))
            # 从 start 起尝试完整匹配；缓冲不足则挂起等下一增量
            match = _TAG_COMPLETE.match(buf, start)
            if match is None:
                if _looks_like_tag_start(buf[start:]):
                    # 可能是合法标记被 chunk 截断（或畸形）：截断处无从判定 → 挂起
                    self._hold = buf[start:]
                    break
                # `[[` 后明显不是 cue 标记 → 按普通文本放行（继续扫描嵌套的 [[）
                out.extend(self._emit_text(buf[start : start + 2]))
                pos = start + 2
                continue
            out.extend(self._take_tag(match.group(1)))
            pos = match.end()
        return out

    def flush(self) -> list[ParserOutput]:
        """流末收口：挂起缓存中合法标记前缀（畸形/半畸形）整段丢弃，其余放行。"""
        out: list[ParserOutput] = []
        if self._hold:
            if _TAG_ATTEMPT.match(self._hold):
                out.extend(self._emit_text(self._drop_malformed_hold()))
            else:
                out.extend(self._emit_text(self._hold))
            self._hold = ""
        return out

    def _drop_malformed_hold(self) -> str:
        """畸形标记残骸的丢弃策略：只丢残骸、尽量保留其后正文。

        流末仍未闭合的标记会一直占用 hold——若整段丢弃，标记后的正常回复
        内容会一并丢失（用户看到回复被截断，实测 2026-09-28）。零泄漏红线
        不变：控制序列本身绝不外泄，只尽可能多保住正文：
        - 含 ``]]``：丢弃到 ``]]``（含），如 ``[[cue:BAD]]正文`` → ``正文``；
        - 无 ``]]``：丢弃标记语法前缀（``[[cue:id``），如
          ``[[cue:sad我很难过`` → ``我很难过``；
        - 连语法都不完整（``[[cue``）：整段丢弃（无法可靠切分）。
        """
        end = self._hold.find("]]")
        if end >= 0:
            self._count(_DROP_MALFORMED)
            return self._hold[end + 2 :]
        prefix = _MALFORMED_PREFIX.match(self._hold)
        self._count(_DROP_MALFORMED)
        return self._hold[prefix.end() :] if prefix else ""

    # -- 内部 ---------------------------------------------------------------

    def _emit_text(self, text: str) -> list[ParserOutput]:
        """放行清洗文本并推进分句计数。

        末尾终止符串（如"你好！"的"！"）在本段内无法确认句子是否完成——
        下一增量可能仍是终止符（"！！"折叠）或正文（确认完成）。故暂存为
        pending_tail，与下一段文本拼接后重算：正文到达即确认前段边界。
        """
        if not text:
            return []
        merged = self._pending_tail + text
        if not self._emitted_any_text:
            # 首段：开头连续终止符折叠为 0 个边界（无前置句子）
            merged = merged.lstrip("".join(sorted(_SENTENCE_TERMINATORS)))
        tail = self._trailing_boundary_run(merged)
        self._sentences_done += _count_boundaries(merged, tail)
        self._pending_tail = tail
        self._emitted_any_text = True
        return [ParserOutput(kind="text", text=text)]

    def _trailing_boundary_run(self, text: str) -> str:
        """返回 text 末尾的连续终止符串（跨增量折叠边界用；无则空串）。"""
        i = len(text)
        while i > 0 and text[i - 1] in _SENTENCE_TERMINATORS:
            i -= 1
        return text[i:]

    def _take_tag(self, raw_id: str) -> list[ParserOutput]:
        """白名单校验 + 构造 cue；越权/未知丢弃计数（不产文本）。"""
        # 标记前的句末终止符（pending_tail）此时已确认完成——标记即位于下一句
        if self._pending_tail:
            self._sentences_done += 1
            self._pending_tail = ""
        action_id = raw_id.strip()
        if action_id not in _AGENT_SELECTABLE and action_id not in _FACE_EMOTIONS:
            self._count(_DROP_UNKNOWN)
            logger.info("character.cue 丢弃（非白名单 id）：%s", action_id)
            return []
        if action_id == "idle_neutral":  # 理论被上面分支覆盖；显式双保险
            self._count(_DROP_TERMINAL)
            return []
        self._cue_count += 1
        if self._cue_count > MAX_CUES_PER_REPLY:
            self._count(_DROP_CAP)
            return []
        if not self._emitted_any_text:
            sync, sentence_index = "speech_start", 1
        else:
            sync, sentence_index = "sentence_boundary", self._sentences_done + 1
        channels: CueChannels = (
            CueChannels(face=CueFaceChannel(emotion=action_id, intensity=REPLY_CUE_INTENSITY))
            if action_id in _FACE_EMOTIONS
            else CueChannels(body=CueBodyChannel(action_id=action_id))
        )
        return [
            ParserOutput(
                kind="cue",
                cue=CharacterCueData(
                    cue_id=f"c-{uuid.uuid4().hex[:12]}",
                    run_id=self._run_id,
                    message_id=self._message_id,
                    source="reply",
                    channels=channels,
                    sync=sync,
                    sentence_index=sentence_index,
                    priority=REPLY_CUE_PRIORITY,
                    # 字面量收敛（Literal 类型仅一个合法值，防御未来扩展）
                    interrupt_policy=CUE_INTERRUPT_POLICY_VALUES[0],
                    ttl_ms=REPLY_CUE_TTL_MS,
                ),
            )
        ]

    def _count(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1


def _looks_like_tag_start(fragment: str) -> bool:
    """`[[` 开头且（忽略空白、大小写）与 "[[cue" 互为前缀 → 标记尝试（含截断）。

    截断例：`[[c`、`[[ cu`（下一增量可能补全为合法标记，须挂起等待）；
    非标记例：`[[code]]`、`[[queue`（前缀不吻合 → 按普通文本放行）。
    """
    f = re.sub(r"\s+", "", fragment).lower()[: len(_ATTEMPT_LITERAL) + 1]
    return _ATTEMPT_LITERAL.startswith(f) or f.startswith(_ATTEMPT_LITERAL)


def _count_boundaries(text: str, exclude_tail: str) -> int:
    """统计 text 中的分句边界数；末尾连续终止符不算完成（跨增量折叠）。"""
    body = text[: len(text) - len(exclude_tail)] if exclude_tail else text
    count = 0
    prev_boundary = False
    for ch in body:
        if ch in _SENTENCE_TERMINATORS:
            if not prev_boundary:
                count += 1
            prev_boundary = True
        else:
            prev_boundary = False
    return count


def cue_prompt_section() -> str:
    """注入 system prompt 的标记使用说明（仅 cue 路径启用时拼接）。"""
    body_ids = ", ".join(sorted(_AGENT_SELECTABLE))
    face_ids = ", ".join(sorted(_FACE_EMOTIONS))
    return (
        "\n\n# 表演标记（可选）\n"
        "你可以在回复的句子开头插入标记，让角色做出对应的动作或表情：\n"
        f"- 动作标记：[[cue:id]]，id 可选：{body_ids}\n"
        f"- 表情标记：[[cue:emotion]]，emotion 可选：{face_ids}\n"
        "用法约束：整个回复至多 2~3 个标记；标记放在它所描述的句子开头；"
        "不要连续使用、不要解释标记、不要把标记放进引用或列表。"
    )
