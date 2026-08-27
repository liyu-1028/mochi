"""上下文预算裁剪（M1-S4 后半，功能清单 4.4）：长对话不报错，截断对用户无感。

策略（宁保守不越限）：
- **token 估算启发式**（不引 tokenizer 依赖，打包体积红线）：
  CJK 字符 ≈ 1 token/字；其余（Latin/数字/符号）≈ 1 token/4 字符；加每条
  消息固定开销（角色标记等，对齐各家 chat 模板量级）。
- **预算公式**：provider ``context_window``（缺省 8192）− system/记忆段实际
  估算 − 本轮 user 输入 − 安全余量（25%：估算误差 + 回复预留 + 工具声明）。
- **裁剪算法**：从最新往旧累加，超出预算即截；被裁掉的部分以一条
  ``[较早的对话已省略 N 条]`` 系统侧标记开头注入，保对话连贯可读。
- 兜底：单条消息超预算时保留其尾部（最新内容通常在尾）；历史全裁也保
  system + 本轮 user——模型侧报 ERR_CONTEXT_OVERFLOW 时由既有错误映射
  兜底（6.7），双保险。

验收对应（4.4）：「接近上下文上限自动摘要/截断，对用户无感」——截断即达标，
LLM 滚动摘要列为后续增强（m1-completion-plan B1b）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .adapters.base import ChatMessage

#: 每条消息固定开销（token）：角色/分隔标记等，量级对齐各家 chat 模板
_PER_MESSAGE_OVERHEAD = 8

#: 安全余量比例：估算误差 + 回复预留 + 工具声明占用
_SAFETY_MARGIN_RATIO = 0.25

#: 缺省上下文窗口（provider 未声明 context_window 时）
_DEFAULT_CONTEXT_WINDOW = 8192


def _is_wide(ch: str) -> bool:
    """全角字符（CJK 统一表意 + CJK 符号 + 全角形式）：按 1 token 计。"""
    return (
        ("\u4e00" <= ch <= "\u9fff") or ("\u3000" <= ch <= "\u303f") or ("\uff00" <= ch <= "\uffef")
    )


def estimate_tokens(text: str) -> int:
    """启发式 token 估算：CJK ≈ 1/字，其余 ≈ 1/4 字符。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_wide(ch))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def estimate_messages_tokens(messages: list[ChatMessage]) -> int:
    return sum(estimate_tokens(m["content"]) + _PER_MESSAGE_OVERHEAD for m in messages)


@dataclass(frozen=True)
class ContextBudget:
    """一轮对话的预算构成（排查与测试可读）。"""

    context_window: int
    reserved: int  # system + 记忆段 + 本轮 user 的估算
    margin: int  # 安全余量
    available: int  # 历史消息可用预算

    @property
    def description(self) -> str:
        return (
            f"window={self.context_window} reserved={self.reserved} "
            f"margin={self.margin} available={self.available}"
        )


def compute_budget(
    system_text: str,
    user_text: str,
    *,
    context_window: int | None = None,
) -> ContextBudget:
    """按窗口与占用算历史可用预算；窗口非法（≤0）回退缺省。"""
    window = context_window if context_window and context_window > 0 else _DEFAULT_CONTEXT_WINDOW
    reserved = (
        estimate_tokens(system_text)
        + _PER_MESSAGE_OVERHEAD  # system
        + estimate_tokens(user_text)
        + _PER_MESSAGE_OVERHEAD  # 本轮 user
    )
    margin = max(1, int(window * _SAFETY_MARGIN_RATIO))
    available = max(0, window - reserved - margin)
    return ContextBudget(
        context_window=window, reserved=reserved, margin=margin, available=available
    )


def trim_history(
    history: list[ChatMessage],
    budget: ContextBudget,
) -> tuple[list[ChatMessage], int]:
    """从最新往旧装入预算；返回 (裁剪后历史, 被裁条数)。

    返回的历史保持原时间序；被裁时由调用方注入省略标记（本函数不拼
    system，职责单一）。单条超预算的巨消息保留尾部（内容新者居尾）。
    """
    kept_reversed: list[ChatMessage] = []
    used = 0
    for msg in reversed(history):
        cost = estimate_tokens(msg["content"]) + _PER_MESSAGE_OVERHEAD
        if used + cost > budget.available:
            if not kept_reversed:
                # 首条（最新）即超预算：保尾部（预算内最长后缀）
                room = max(0, budget.available - _PER_MESSAGE_OVERHEAD)
                if room > 0:
                    text = msg["content"]
                    tail = _tail_within_tokens(text, room)
                    kept_reversed.append({"role": msg["role"], "content": tail})
            break
        used += cost
        kept_reversed.append(msg)
    kept = list(reversed(kept_reversed))
    return kept, len(history) - len(kept)


def _tail_within_tokens(text: str, token_budget: int) -> str:
    """取字符串的 token 预算内最长后缀（近似：从尾部逐字符累积）。"""
    if estimate_tokens(text) <= token_budget:
        return text
    acc = 0
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        acc += 1 if _is_wide(ch) else 0.25
        if acc > token_budget:
            return text[i + 1 :]
    return text


def build_context_messages(
    system_text: str,
    history: list[ChatMessage],
    user_text: str,
    *,
    context_window: int | None = None,
) -> tuple[list[ChatMessage], ContextBudget, int]:
    """4.4 主入口：组装 system + 裁剪后历史 + 本轮 user。

    返回 (messages, budget, dropped)；dropped > 0 时历史头部注入省略标记
    （角色 system、置于历史首，与记忆段同风格，避免污染 assistant 轮次）。
    """
    budget = compute_budget(system_text, user_text, context_window=context_window)
    kept, dropped = trim_history(history, budget)
    messages: list[ChatMessage] = [{"role": "system", "content": system_text}]
    if dropped > 0:
        messages.append({"role": "system", "content": f"[较早的对话已省略 {dropped} 条]"})
    messages.extend(kept)
    messages.append({"role": "user", "content": user_text})
    return messages, budget, dropped
