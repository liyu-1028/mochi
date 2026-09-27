"""意图与决策模型（M-D）：注意力层的数据词汇。

意图（Intent）是注意力层的第一阶段产物，four kinds（调研报告 §4.1）：
- ``silent``      ：观察到但不行动（仅更新引擎内部状态）；
- ``action_intent``：只做动作（上层映射 character.cue，source=proactive）；
- ``speak_intent`` ：主动说话（上层起 proactive run，LangGraph 措辞）；
- ``ask_intent``   ：主动提问（同上 + 快速操作 + 无声过期 + 未回应衰减）。

GateDecision 是第二阶段（门控）产物：allow 或 suppress(原因)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

IntentKind = Literal["silent", "action_intent", "speak_intent", "ask_intent"]
IntentAction = Literal["speak", "ask"]
QuickReply = Literal["later", "dismiss"]


@dataclass(slots=True)
class Signal:
    """companion.signal 的引擎内部形态（字段与协议 CompanionSignalData 一致）。"""

    signal_id: str
    kind: str
    occurred_at: int
    salience: int  # 0~3
    dedupe_key: str | None = None
    not_before: int | None = None
    expires_at: int | None = None
    payload: dict = field(default_factory=dict)


@dataclass(slots=True)
class Intent:
    """注意力层第一阶段产物。speak/ask 经门控后由上层执行；action 带动作 id。"""

    intent_id: str
    kind: IntentKind
    signal: Signal
    action: IntentAction | None = None  # speak/ask 时必填
    action_id: str | None = None  # action_intent 时必填（白名单语义动作 id）
    dedupe_key: str | None = None  # 同主题冷却键（继承信号）
    expires_at: int | None = None  # ask_intent 的无声过期时刻
    quick_replies: tuple[QuickReply, ...] = ()  # ask_intent 的快速操作
    priority: int = 1  # 0=低（可被用户活动取消）1=普通
    trigger_prompt: str = ""  # 给 LangGraph 的触发上下文（proactive run 用，不落盘）


@dataclass(slots=True)
class GateDecision:
    """门控结果：allow 放行执行；suppress 带原因（日志计数用，不外发）。"""

    allowed: bool
    reason: str | None = None  # suppress 原因：规则名

    @classmethod
    def allow(cls) -> GateDecision:
        return cls(True)

    @classmethod
    def suppress(cls, reason: str) -> GateDecision:
        return cls(False, reason)
