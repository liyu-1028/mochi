"""MemoryManager —— 记忆自动沉淀与召回编排（M1-S3，功能清单 6.4）。

职责：
- **召回**（recall）：对话前按用户输入 FTS 检索相关记忆，拼装为 system prompt 补充段；
- **沉淀**（extract_and_store）：对话后用 LLM 提取值得记住的事实/偏好，写入 SQLite。

设计要点：
- 沉淀走异步 fire-and-forget（不阻塞回复），失败静默降级（6.7 优雅降级）；
- 试用模式（无 adapter）跳过沉淀，仅保留手动记忆能力；
- 记忆去重：新记忆与已有记忆内容相似（子串包含）时跳过，避免膨胀。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from ..store import SessionStore

if TYPE_CHECKING:
    from ..agent.adapters.base import ChatMessage, ProviderAdapter

logger = logging.getLogger(__name__)

# 召回上限：注入 system prompt 的记忆条数（过多会挤占上下文窗口）。
_RECALL_LIMIT = 5

# 沉淀提示词：要求 LLM 输出 JSON 数组，严格约束格式以降低解析失败率。
#: 每日自动沉淀上限（6.4 质量闸门）：超出后当日只保留召回与手动能力
_DAILY_AUTO_LIMIT = 20
_EXTRACT_SYSTEM = (
    "你是一个记忆提取助手。从以下对话中提取值得长期记住的用户信息。\n"
    "只提取关于用户的事实和偏好，忽略寒暄和一次性问题。\n"
    "每条记忆用一句简短的话描述。\n"
    "输出 JSON 数组，每项格式为："
    '{"category": "fact"或"preference", "content": "简短描述"}\n'
    "如果没有值得记住的信息，输出空数组 []。\n"
    "只输出 JSON，不要其他内容。"
)


class MemoryManager:
    """记忆生命周期管理：召回 + 沉淀。"""

    def __init__(self, store: SessionStore, *, auto_extract: bool = True) -> None:
        self._store = store
        # 自动沉淀开关（6.4，v0.7.1 回退后重开）：False → 仅手动记忆
        self._auto_extract = auto_extract

    @property
    def auto_extract(self) -> bool:
        return self._auto_extract

    # -- 召回 ----------------------------------------------------------------

    async def recall_for_prompt(self, user_text: str) -> str:
        """检索与用户输入相关的记忆，返回拼装好的 prompt 段落（无记忆时返回空串）。"""
        try:
            memories = await self._store.search_memories(user_text, limit=_RECALL_LIMIT)
        except Exception:
            logger.exception("记忆召回失败，降级为无记忆上下文")
            return ""
        if not memories:
            return ""
        return self.format_memories(memories)

    @staticmethod
    def format_memories(memories: list[dict]) -> str:
        """把记忆列表格式化为 system prompt 补充段落。"""
        lines = ["\n\n## 关于用户的记忆（请自然地参考，不要生硬复述）"]
        category_label = {"fact": "事实", "preference": "偏好"}
        for m in memories:
            label = category_label.get(m["category"], m["category"])
            lines.append(f"- [{label}] {m['content']}")
        return "\n".join(lines)

    # -- 沉淀 ----------------------------------------------------------------

    async def extract_and_store(self, adapter: ProviderAdapter, user_text: str, reply: str) -> None:
        """异步提取记忆并落盘。失败静默降级，不影响对话流程。

        质量闸门（v0.7.1 回退教训，6.4 重开）：
        - auto_extract=False 直接跳过；
        - 每日自动沉淀上限（_DAILY_AUTO_LIMIT）：防止提取质量不稳时爆库，
          用户仍可手动无上限添加。
        """
        if not self._auto_extract:
            return
        try:
            if await self._daily_auto_count() >= _DAILY_AUTO_LIMIT:
                logger.info("今日自动沉淀已达上限 %d 条，跳过（手动添加不受限）", _DAILY_AUTO_LIMIT)
                return
            raw = await self._call_extract(adapter, user_text, reply)
            items = self._parse_extract_response(raw)
            if not items:
                return
            existing = await self._store.list_memories()
            existing_contents = {m["content"] for m in existing}
            for item in items:
                content = item.get("content", "").strip()
                if not content or content in existing_contents:
                    continue
                category = item.get("category", "fact")
                if category not in ("fact", "preference"):
                    category = "fact"
                memory_id = f"mem-{uuid.uuid4().hex[:12]}"
                await self._store.add_memory(memory_id, category, content, source="auto")
                existing_contents.add(content)
            logger.info("记忆沉淀完成：%d 条", len(items))
        except Exception:
            logger.exception("记忆自动沉淀失败（不影响对话）")

    async def _daily_auto_count(self) -> int:
        """今日（本地时区）自动沉淀条数；存储异常降级为 0（不阻断沉淀）。"""
        try:
            memories = await self._store.list_memories()
        except Exception:
            logger.exception("统计今日沉淀失败，按 0 处理")
            return 0
        today_start = (
            datetime.now()
            .astimezone()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
            * 1000
        )
        return sum(
            1
            for m in memories
            if m.get("source") == "auto" and (m.get("createdAt") or 0) >= today_start
        )

    async def _call_extract(self, adapter: ProviderAdapter, user_text: str, reply: str) -> str:
        """调用 LLM 提取记忆，收集完整输出文本。"""
        messages: list[ChatMessage] = [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": f"用户说：{user_text}\n助手回复：{reply}"},
        ]
        parts: list[str] = []
        async for _kind, delta in adapter.stream_chat(messages, run_id="memory-extract"):
            parts.append(delta)
        return "".join(parts)

    @staticmethod
    def _parse_extract_response(raw: str) -> list[dict]:
        """解析 LLM 的 JSON 数组输出；容错：剥离 markdown 围栏与非 JSON 文本。"""
        text = raw.strip()
        # 剥离 ```json ... ``` 围栏
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()
        # 定位 JSON 数组边界
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            logger.warning("记忆提取 JSON 解析失败：%s", text[:200])
        return []
