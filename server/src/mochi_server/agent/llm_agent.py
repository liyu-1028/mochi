"""LLMAgentService —— 真实 LLM 的 AgentService 实现（M0-S2 起，M1-S4 换图内核）。

M1-S4（ADR-0008）：内核换为自搭 ReAct 图（react_graph.build_react_graph），
AgentService 接口与 RunManager 零改动——「前后端只依赖协议」红利的兑现。
协议事件序列保持既有形状（黄金样例 packages/protocol/testdata/
turn-with-tool-call.jsonl）：

    state.change(thinking) → thinking.start → [thinking.delta...] → thinking.end
    （若有工具）state.change(working) → tool.call.start → tool.call.end
    state.change(talking) → emotion(neutral) → text.start → [text.delta...]
    → text.end → state.change(idle)

事件桥：graph.astream(stream_mode=["messages","custom"])——messages 通道
的 AIMessageChunk 经 _deltas_from_chunk 分拣为 thinking/text 增量；custom
通道携带 tools 节点实时写出的工具事件。thinking 骨架先行；首个正文增量
收思考、切说话（对齐 M1-S0 起的既有时序）。回环中后续阶段的 thinking
增量在思考已收口后不再补发（协议一回合一条思考流）。

emotion 策略（ADR-0002 D5）：固定 neutral/0.5；真实情绪推断推迟专项。
多轮历史（M1-S1，4.3/6.2）：SessionStore 注入后按 session_id 取最近 N 条
拼装上下文，回合完成后落盘——**历史以 store 为唯一事实源**，checkpoint
thread_id 用 run_id（非 session_id），避免与图内消息双计（ADR-0008 D4）。
记忆（M1-S3，6.4）：MemoryManager 注入后，对话前召回相关记忆注入 system
prompt；当前版本仅手动添加，自动提取留后续版本。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from ..events import (
    Emotion,
    EmotionData,
    ErrorCode,
    ErrorPayload,
    StateChangeData,
    TextDeltaData,
    TextEndData,
    TextStartData,
    ThinkingDeltaData,
    ThinkingEndData,
    ThinkingStartData,
    ToolCallEndData,
    ToolCallStartData,
)
from ..memory import MemoryManager
from ..persona import DEFAULT_SYSTEM_PROMPT
from ..store import HISTORY_LIMIT, SessionStore
from .adapters.base import ChatMessage
from .adapters.langchain import LangChainAdapter, _deltas_from_chunk, _to_lc_messages
from .context import build_context_messages
from .cue_extractor import CueStreamParser, cue_prompt_section
from .emotion import classify_reply_emotion
from .errors import AgentError
from .react_graph import build_react_graph, is_llm_chunk
from .service import AgentContext, AgentEvent, AgentService
from .stage_directions import StageDirectionScanner
from .tools import ToolPolicy, ToolRegistry

logger = logging.getLogger(__name__)

#: 工具使用提示（M1-S4 任务 9）：小模型带人格 system prompt 时易把工具调用
#: 当纯文本输出甚至编造结果（实测 qwen2.5:1.5b，2026-08-19），绑定工具时追加。
#: 零行为变更：无工具（tool_registry=None）不拼接，黄金样例回放不变。
_TOOL_NUDGE = (
    "\n你可以调用提供的工具完成任务（如查询时间、读取文件）。"
    "需要外部信息或执行操作时务必调用工具，绝不要编造工具结果。"
)

#: 后置情绪强度（2.5）：非中性情绪统一 0.75（显著但不过火）
_EMOTION_INTENSITY = 0.75

#: 单回合回复文本上限的缺省值（字符数，cue 清洗后正文，不含动作标记）：
#: 实际值来自 [agent].max_reply_chars（用户可在设置中调整，50–4000）。
#: 桌宠气泡与 TTS 的阅读尺度决定了长回复没有价值（气泡内滚 + 朗读拖沓）；
#: 超限文本丢弃、以「…」收尾，并在 system prompt 中同步告知模型真实上限。
#: 配套前端气泡正文最大高度（styles.css .bubble__body）。
#: cue 标记不受影响——解析器照常喂入，尾部动作标记照常触发。
DEFAULT_MAX_REPLY_CHARS = 200


def reply_length_requirement(cap: int) -> str:
    """system prompt 中的回复长度硬性要求片段（run() 与测试共用事实源）。"""
    return (
        f"\n\n[回复长度硬性要求] 单次回复不超过 {cap} 个字符。"
        "超出部分会被系统丢弃；请把内容精炼在限额内，宁可短小完整，不要长篇大论。"
    )


def _capped_slice(cap: int, emitted: int, delta: str) -> str:
    """回复长度封顶的纯函数：返回本次允许放行的文本（可能为切片或空串）。

    ``cap`` 为本回合上限（用户可配）；``emitted`` 为已放行字符数；
    返回值长度 ≤ ``cap - emitted``。调用方以「返回长度 < len(delta)」判定截断。
    """
    if emitted >= cap:
        return ""
    return delta[: cap - emitted]


@dataclass
class _PendingConfirm:
    """挂起等待用户裁决的危险工具调用（run_id → 本表）。"""

    tool_call_id: str
    name: str
    future: asyncio.Future[tuple[str, bool]]  # (decision, remember)


class LLMAgentService(AgentService):
    """组合 ReAct 图与协议事件流。"""

    def __init__(
        self,
        adapter: LangChainAdapter,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        store: SessionStore | None = None,
        memory_manager: MemoryManager | None = None,
        tool_registry: ToolRegistry | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        tool_policy: ToolPolicy | None = None,
        context_window: int | None = None,
        emotion_enabled: bool = True,
        cue_enabled: bool = False,
        max_reply_chars: int = DEFAULT_MAX_REPLY_CHARS,
    ):
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._store = store
        self._memory = memory_manager
        self._tools = tool_registry  # None → 图不 bind_tools，纯对话行为
        self._checkpointer = checkpointer  # 任务 7 确认暂停/崩溃恢复（ADR-0008 D4）
        self._policy = tool_policy  # None → 危险工具不确认（直接执行）
        self._context_window = context_window  # 4.4 预算裁剪；None → 缺省 8192
        self._emotion_enabled = emotion_enabled  # 2.5 情绪后置；False → 不分类
        # 表演节拍（M-C）：默认 False（黄金样例/既有测试零影响）；registry 按配置开启
        self._cue_enabled = cue_enabled
        # 回复长度上限（2026-09-28 用户可配）：流式放行 + system prompt 双侧生效
        self._max_reply_chars = max_reply_chars
        self._pending: dict[str, _PendingConfirm] = {}
        # 后台任务（6.4 记忆提取）持引用，防 fire-and-forget 被 GC 中途回收
        self._background: set[asyncio.Task[None]] = set()
        # run_id → 本轮回复（post_run_events 消费；仅完整回合暂存）
        self._last_reply: dict[str, str] = {}

    @property
    def adapter(self) -> LangChainAdapter:
        return self._adapter

    async def _load_history(self, session_id: str) -> list[ChatMessage]:
        """取最近 N 条历史消息；存储故障降级为无历史，不阻断对话（6.7 优雅降级）。"""
        if self._store is None:
            return []
        try:
            return [
                {"role": m["role"], "content": m["content"]}
                for m in await self._store.recent_messages(session_id, limit=HISTORY_LIMIT)
            ]
        except Exception:
            logger.exception("读取会话历史失败，降级为单轮：session_id=%s", session_id)
            return []

    async def _persist_assistant_only(self, session_id: str, reply: str) -> None:
        """proactive 回合落盘（M-D D4）：只记录真正说出的 assistant utterance。"""
        if self._store is None:
            return
        try:
            await self._store.append_message(session_id, "assistant", reply)
        except Exception:
            logger.exception("主动回复落盘失败（不影响本回合）：session_id=%s", session_id)

    async def _persist_turn(self, session_id: str, user_text: str, reply: str) -> None:
        if self._store is None:
            return
        try:
            await self._store.append_message(session_id, "user", user_text)
            await self._store.append_message(session_id, "assistant", reply)
        except Exception:
            logger.exception("会话落盘失败（不影响本回合回复）：session_id=%s", session_id)

    async def run(self, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        message_id = f"m-{uuid.uuid4().hex[:12]}"
        proactive = ctx.source == "proactive"

        # 记忆召回（6.4）：按用户输入检索相关记忆，注入 system prompt；
        # proactive 回合无用户输入（ctx.text 是引擎触发指令），跳过检索
        memory_section = ""
        if self._memory is not None and not proactive:
            memory_section = await self._memory.recall_for_prompt(ctx.text)

        # 多轮拼装（6.2）+ 上下文预算（4.4）：system + 预算内历史 + 本轮 user；
        # 超限自动截断并注入省略标记，长对话不报错、对用户无感
        history = await self._load_history(ctx.session_id)
        effective_system = self._system_prompt + memory_section
        if proactive:
            # M-D：触发上下文由引擎生成（不落盘），模型以「主动关心/提醒」
            # 姿态回复，不假装在回答用户问题
            effective_system += (
                "\n\n（当前是你主动开口的时刻：下面这条消息是系统触发的关心/提醒"
                "上下文，不是用户发言。请用符合你性格的方式自然地说出来。）"
            )
        if self._tools is not None and self._tools.list_specs():
            effective_system += _TOOL_NUDGE
        if self._cue_enabled:
            effective_system += cue_prompt_section()
        # 回复长度硬性要求（2026-09-28 用户可配）：同步告知模型真实上限，
        # 否则模型会自行宣称/按其它长度标准作答（实测：被 200 截断却自称 300~500 字）
        effective_system += reply_length_requirement(self._max_reply_chars)
        messages, budget, dropped = build_context_messages(
            effective_system, history, ctx.text, context_window=self._context_window
        )
        if dropped:
            logger.info("上下文裁剪：%s dropped=%d", budget.description, dropped)

        # --- 思考阶段骨架先行（真实推理流经 messages 通道注入） ---
        yield "state.change", StateChangeData(state="thinking")
        yield "thinking.start", ThinkingStartData(run_id=ctx.run_id, message_id=message_id)

        thinking_closed = False
        text_started = False
        parts: list[str] = []
        # 回复长度封顶（[agent].max_reply_chars）：emitted=已放行字符数，truncated=是否丢弃过文本
        reply_cap = self._max_reply_chars
        emitted_chars = 0
        reply_truncated = False
        cue_source = "proactive" if proactive else "reply"
        cue_parser = (
            CueStreamParser(ctx.run_id, message_id, source=cue_source)
            if self._cue_enabled
            else None
        )
        # 舞台指示扫描器（M-F）：与标记解析器平行运行，吃同一清洗流，
        # 把「（眨眨眼）」式描写转成 character.cue（文本零改动）
        direction_scanner = (
            StageDirectionScanner(ctx.run_id, message_id, source=cue_source)
            if cue_parser is not None
            else None
        )
        cue_emitted = False  # 本 run 已发 reply cue → 与迟到 emotion 分类互斥

        graph = build_react_graph(
            self._adapter.chat_model,
            self._tools or ToolRegistry(),
            checkpointer=self._checkpointer,
            policy=self._policy,
        )
        config = {"configurable": {"thread_id": ctx.run_id}}
        # 危险确认（任务 7，6.5）：interrupt 挂起 → 流结束 → 等用户裁决 →
        # Command(resume=…) 续跑。resume 会重放 tools 节点（实证 2026-08-18），
        # start 事件按 tool_call_id 去重。
        stream_input: object = {
            "messages": _to_lc_messages(messages, anthropic_style=self._adapter.needs_role_merge)
        }
        emitted_starts: set[str] = set()
        pending_call_id: str | None = None
        pending_name: str = ""
        try:
            while True:
                pending_call_id = None  # 每轮流内跟踪；流结束仍非 None 即挂起
                async for mode, payload in graph.astream(
                    stream_input, config, stream_mode=["messages", "custom"]
                ):
                    if mode == "custom":
                        kind = payload.get("kind")
                        if kind == "tool_call_start":
                            tc_id = payload["tool_call_id"]
                            if tc_id in emitted_starts:
                                continue  # resume 轮重放去重
                            emitted_starts.add(tc_id)
                            if payload.get("requires_confirmation"):
                                pending_call_id = tc_id
                                pending_name = payload["name"]
                                # 竞态修复（任务 9 实测 2026-08-19）：挂起项必须在
                                # 事件发出前注册——客户端最快收到 tool.call.start 即回
                                # tool.confirm，若等流结束才注册（_await_confirmation），
                                # 早到确认会被丢弃 → 回合死锁。图内危险调用顺序处理，
                                # 同一 run 同时至多一个挂起项，单键安全。
                                self._pending[ctx.run_id] = _PendingConfirm(
                                    tc_id,
                                    payload["name"],
                                    asyncio.get_running_loop().create_future(),
                                )
                        elif kind == "tool_call_end" and pending_call_id == payload.get(
                            "tool_call_id"
                        ):
                            pending_call_id = None  # deny 由图内收口，本轮已闭合
                        # 黄金样例时序：thinking.end → state.change(working) → tool.call.start
                        for event_type, event_payload in self._bridge_custom(
                            ctx, payload, message_id, thinking_closed
                        ):
                            if event_type == "thinking.end":
                                thinking_closed = True
                            yield event_type, event_payload
                        continue
                    if not is_llm_chunk(payload):
                        continue
                    chunk: AIMessageChunk = payload[0]
                    for kind, delta in _deltas_from_chunk(chunk):
                        if kind == "thinking":
                            if not thinking_closed:
                                yield (
                                    "thinking.delta",
                                    ThinkingDeltaData(
                                        run_id=ctx.run_id, message_id=message_id, delta=delta
                                    ),
                                )
                        else:
                            if not text_started:
                                # 仅首个正文增量前收思考、切说话（后续 delta 直发）
                                for event_type, event_payload in self._open_text_phase(
                                    ctx, message_id, thinking_closed
                                ):
                                    if event_type == "thinking.end":
                                        thinking_closed = True
                                    elif event_type == "text.start":
                                        text_started = True
                                    yield event_type, event_payload
                            if cue_parser is None:
                                # cue 路径关闭：原始增量直发（M-B 行为，长度封顶）
                                piece = _capped_slice(reply_cap, emitted_chars, delta)
                                emitted_chars += len(piece)
                                reply_truncated = reply_truncated or len(piece) < len(delta)
                                if piece:
                                    parts.append(piece)
                                    yield (
                                        "text.delta",
                                        TextDeltaData(
                                            run_id=ctx.run_id,
                                            message_id=message_id,
                                            delta=piece,
                                            source=ctx.source,
                                        ),
                                    )
                            else:
                                # cue 路径（M-C）：增量经标记解析器清洗——
                                # 文本增量只含清洗后文本（标记不进气泡/TTS/落盘）；
                                # 长度封顶只丢文本，cue 输出不受影响
                                for out in cue_parser.feed(delta):
                                    if out.kind == "text":
                                        piece = _capped_slice(reply_cap, emitted_chars, out.text)
                                        emitted_chars += len(piece)
                                        reply_truncated = reply_truncated or len(piece) < len(
                                            out.text
                                        )
                                        if piece:
                                            parts.append(piece)
                                            yield (
                                                "text.delta",
                                                TextDeltaData(
                                                    run_id=ctx.run_id,
                                                    message_id=message_id,
                                                    delta=piece,
                                                    source=ctx.source,
                                                ),
                                            )
                                            if direction_scanner is not None:
                                                for cue in direction_scanner.feed(piece):
                                                    cue_emitted = True
                                                    yield "character.cue", cue
                                    else:
                                        cue_emitted = True
                                        yield "character.cue", out.cue
                if pending_call_id is None:
                    break  # 真完成（或本轮流内已闭合确认）
                # 挂起：等用户裁决。cancel → CancelledError 经 await 自然传播；
                # generator 未结束 → RunManager 不会发 run.finished（暂停非完成）。
                decision, remember = await self._await_confirmation(
                    ctx, pending_call_id, pending_name
                )
                # remember 语义：仅 allow 生效（协议只定义「总是允许」，deny 每次重问）
                if decision == "allow" and remember and self._policy is not None:
                    self._policy.allow_always(pending_name)
                stream_input = Command(resume={"decision": decision})
        except AgentError:
            raise
        except Exception as exc:  # 图内模型异常收敛为 AgentError（RunManager 消费）
            raise self._adapter.translate_error(exc) from exc
        finally:
            # 预注册配套：取消/异常路径也清挂起表（正常路径 _await_confirmation
            # 的 finally 已清，此处兑底幂等）
            self._pending.pop(ctx.run_id, None)

        if not text_started:
            # 空响应（或纯 thinking/纯工具无正文）：仍走完骨架，保协议时序完整
            for event_type, event_payload in self._open_text_phase(
                ctx, message_id, thinking_closed
            ):
                yield event_type, event_payload

        # cue 路径：流末收口解析器（畸形标记丢弃、非标记残余放行为文本增量）
        if cue_parser is not None:
            for out in cue_parser.flush():
                if out.kind == "text":
                    piece = _capped_slice(reply_cap, emitted_chars, out.text)
                    emitted_chars += len(piece)
                    reply_truncated = reply_truncated or len(piece) < len(out.text)
                    if piece:
                        parts.append(piece)
                        yield (
                            "text.delta",
                            TextDeltaData(
                                run_id=ctx.run_id,
                                message_id=message_id,
                                delta=piece,
                                source=ctx.source,
                            ),
                        )
                else:
                    cue_emitted = True
                    yield "character.cue", out.cue
            if cue_parser.dropped:
                logger.info("character.cue 丢弃计数：run_id=%s %s", ctx.run_id, cue_parser.dropped)
            if direction_scanner is not None:
                if direction_scanner.dropped:
                    logger.info(
                        "舞台指示丢弃计数：run_id=%s %s",
                        ctx.run_id,
                        direction_scanner.dropped,
                    )
                for cue in direction_scanner.flush():
                    cue_emitted = True
                    yield "character.cue", cue

        # 长度封顶收尾：发生过截断 → 以「…」收尾（气泡/TTS/落盘一致）
        if reply_truncated:
            parts.append("…")
            yield (
                "text.delta",
                TextDeltaData(
                    run_id=ctx.run_id,
                    message_id=message_id,
                    delta="…",
                    source=ctx.source,
                ),
            )

        full_text = "".join(parts)
        # 落盘本轮（4.3）：仅完整回合入库，取消/出错不落盘；
        # proactive 只落 assistant（D4 记忆边界：不伪造 user message）
        if proactive:
            await self._persist_assistant_only(ctx.session_id, full_text)
        else:
            await self._persist_turn(ctx.session_id, ctx.text, full_text)
        # 记忆自动沉淀（6.4，v0.7.1 回退后重开）：fire-and-forget 不阻塞回合；
        # 开关/每日上限在 MemoryManager 内部闸门；proactive 无用户消息，跳过
        if not proactive:
            self._schedule_extract(ctx.text, full_text)
        # 情绪后置（2.5，ADR-0009）：暂存回复供 post_run_events 分类；
        # run 正常走到这里才会补发，取消/出错路径不暂存（无表情变化）。
        # 互斥（M-C 验收）：本 run 已发 reply cue → 跳过后置分类，
        # 迟到 emotion 不覆盖 cue 表演（前端同规则双保险）
        if not cue_emitted:
            self._last_reply[ctx.run_id] = full_text
        yield (
            "text.end",
            TextEndData(
                run_id=ctx.run_id,
                message_id=message_id,
                full_text=full_text,
                source=ctx.source,
            ),
        )

        # --- 回到待机 ---
        yield "state.change", StateChangeData(state="idle")

    def _schedule_extract(self, user_text: str, reply: str) -> None:
        """后台调度记忆提取；持引用防 GC，异常由 manager 内部静默收敛。"""
        if self._memory is None:
            return

        async def _run() -> None:
            await self._memory.extract_and_store(self._adapter, user_text, reply)

        task = asyncio.create_task(_run())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    # -- 情绪后置（2.5，ADR-0009） -------------------------------------------

    async def post_run_events(self, ctx: AgentContext) -> list[AgentEvent]:
        """回合收口后的情绪补发：单发分类本轮回复，命中非 neutral 才发事件。"""
        reply = self._last_reply.pop(ctx.run_id, "")
        if not self._emotion_enabled or not reply.strip():
            return []
        emotion = await classify_reply_emotion(self._adapter, reply)
        if emotion is None or emotion is Emotion.NEUTRAL:
            return []  # 失败降级/中性：维持 run 内既有 neutral/0.5，零回归
        return [
            (
                "emotion",
                EmotionData(run_id=ctx.run_id, emotion=emotion, intensity=_EMOTION_INTENSITY),
            )
        ]

    # -- 危险确认（任务 7，功能清单 6.5） --------------------------------------

    async def confirm(
        self, run_id: str, tool_call_id: str, decision: str, *, remember: bool = False
    ) -> bool:
        """WS tool.confirm 分发入口；返回 False 表示无匹配的等待中调用（过期确认）。"""
        pending = self._pending.get(run_id)
        if pending is None or pending.tool_call_id != tool_call_id or pending.future.done():
            return False
        pending.future.set_result((decision, remember))
        return True

    def has_pending(self, run_id: str) -> bool:
        """是否存在挂起等待确认的调用（测试同步点）。"""
        return run_id in self._pending

    async def _await_confirmation(
        self, ctx: AgentContext, tool_call_id: str, name: str
    ) -> tuple[str, bool]:
        """等待裁决；返回 (decision, remember)。

        挂起项已在事件发出前预注册（见 run 内竞态修复注释），此处直接消费；
        防御性兑底：缺失/不匹配时重建（理论不可达）。cancel → CancelledError
        经 await 传播（finally 清表）；future 结果由 confirm() 注入。
        """
        pending = self._pending.get(ctx.run_id)
        if pending is None or pending.tool_call_id != tool_call_id:
            future: asyncio.Future[tuple[str, bool]] = asyncio.get_running_loop().create_future()
            self._pending[ctx.run_id] = _PendingConfirm(tool_call_id, name, future)
        else:
            future = pending.future
        try:
            return await future
        finally:
            self._pending.pop(ctx.run_id, None)

    # -- 事件桥辅助 ----------------------------------------------------------

    @staticmethod
    def _open_text_phase(
        ctx: AgentContext, message_id: str, thinking_closed: bool
    ) -> list[AgentEvent]:
        """首个正文增量前的事件组：收思考 → 切说话 → emotion → text.start。"""
        events: list[AgentEvent] = []
        if not thinking_closed:
            events.append(
                ("thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id=message_id))
            )
        events.append(("state.change", StateChangeData(state="talking")))
        events.append(
            ("emotion", EmotionData(run_id=ctx.run_id, emotion=Emotion.NEUTRAL, intensity=0.5))
        )
        events.append(
            (
                "text.start",
                TextStartData(
                    run_id=ctx.run_id,
                    message_id=message_id,
                    source=getattr(ctx, "source", "user"),
                ),
            )
        )
        return events

    @staticmethod
    def _bridge_custom(
        ctx: AgentContext, event: dict, message_id: str, thinking_closed: bool
    ) -> list[AgentEvent]:
        """custom 通道工具事件 → 协议事件（工具前收思考、切工作态）。"""
        kind = event.get("kind")
        if kind == "tool_call_start":
            events: list[AgentEvent] = []
            if not thinking_closed:
                events.append(
                    ("thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id=message_id))
                )
            events.append(("state.change", StateChangeData(state="working")))
            events.append(
                (
                    "tool.call.start",
                    ToolCallStartData(
                        run_id=ctx.run_id,
                        tool_call_id=event["tool_call_id"],
                        name=event["name"],
                        args=event["args"],
                        requires_confirmation=bool(event.get("requires_confirmation")),
                    ),
                ),
            )
            return events
        if kind == "tool_call_end":
            status = event["status"]
            failed = status != "success"
            denied = status == "denied"
            return [
                (
                    "tool.call.end",
                    ToolCallEndData(
                        run_id=ctx.run_id,
                        tool_call_id=event["tool_call_id"],
                        status=status,
                        result=None if failed else event["output"],
                        error=(
                            ErrorPayload(
                                code=ErrorCode.TOOL_DENIED if denied else ErrorCode.TOOL_FAILED,
                                message=event["output"],
                                retryable=not denied,
                            )
                            if failed
                            else None
                        ),
                    ),
                ),
            ]
        logger.warning("未识别的 custom 事件：%s", kind)
        return []
