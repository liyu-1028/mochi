"""情绪推断（M1-S4 后半，功能清单 2.5，ADR-0009）：回复后置分类器。

方案：回复完成后用**独立单发分类调用**判断 assistant 回复文本的整体情绪，
不与主对话流内联——规避 ADR-0002 D5 记录的两个坑（首行标签遵循率不稳、
缓冲解析引入首字延迟）。送达时机：run.finished 之后由 RunManager 补发
（不阻塞回合收口与 TTS），协议 §5.6 emotion 的 runId 可选、迟到合法。

降级链（6.7 优雅降级）：分类失败/超时/输出不可解析 → 返回 None，
角色维持默认 neutral/0.5（run 内既有事件），零回归。
"""

from __future__ import annotations

import asyncio
import logging

from ..events import Emotion
from .adapters.base import ProviderAdapter

logger = logging.getLogger(__name__)

#: 分类调用预算：超时即放弃（本地慢模型常态，不拖 UI）；run.finished 已先行
_CLASSIFY_TIMEOUT_S = 2.0

#: 送入分类的文本上限：长回复截断（情绪集中在开头与结尾，取头部即可）
_MAX_INPUT_CHARS = 600

_CLASSIFIER_SYSTEM = (
    "你是情绪分类器。判断下面这段 AI 助手回复的整体情绪倾向，"
    "只输出以下英文单词之一，不要输出任何其他内容：\n"
    "neutral、happy、sad、confused、surprised、embarrassed、angry"
)

_LABELS = frozenset(e.value for e in Emotion)


def parse_emotion_label(raw: str) -> Emotion | None:
    """从分类输出解析情绪标签；容错：剥空白/围栏/杂文，未命中返回 None。"""
    text = raw.strip().strip("`*#").lower()
    for token in text.replace(",", " ").split():
        if token in _LABELS:
            return Emotion(token)
    # 子串兑底：模型可能带前后缀杂文（如「情绪：confused。」）
    for label in _LABELS:
        if label in text:
            return Emotion(label)
    return None


async def classify_reply_emotion(adapter: ProviderAdapter, reply_text: str) -> Emotion | None:
    """对 assistant 回复做一次情绪分类；任何失败返回 None（不外抛）。"""
    text = reply_text.strip()
    if not text:
        return None
    if len(text) > _MAX_INPUT_CHARS:
        text = text[:_MAX_INPUT_CHARS]
    try:
        raw = await asyncio.wait_for(_collect_text(adapter, text), timeout=_CLASSIFY_TIMEOUT_S)
        return parse_emotion_label(raw)
    except TimeoutError:
        return None  # 本地慢模型常态，静默降级
    except Exception:
        logger.exception("情绪分类失败，降级为 neutral")
        return None


async def _collect_text(adapter: ProviderAdapter, text: str) -> str:
    """单发分类调用，收集完整正文（思考流不参与）。"""
    messages = [
        {"role": "system", "content": _CLASSIFIER_SYSTEM},
        {"role": "user", "content": text},
    ]
    parts: list[str] = []
    async for kind, delta in adapter.stream_chat(messages, run_id="emotion-classify"):
        if kind == "text":
            parts.append(delta)
    return "".join(parts)
