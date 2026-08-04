"""SessionStore —— 会话/消息的 SQLite 持久化（M1-S1，功能清单 4.3/6.2）。

设计要点：
- **轻量迁移，不引入 Alembic**：``schema_version`` 表记录当前版本，
  ``_MIGRATIONS`` 按版本号顺序补齐 DDL，迁移函数幂等（调研结论 A5：
  首张表即立 migration 规矩，S4 的 memories 表沿用同一机制）。
- **单连接 + 全局锁**：本地单用户低并发场景，串行化读写最简单可靠，
  避免多连接写同一库触发 "database is locked"。
- **懒打开**：构造不做 I/O，首次访问才连接；便于 create_app 期装配与测试注入。
- 时间戳统一 epoch 毫秒，与协议帧 ``ts`` / main.py ``_now_ms`` 一致。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import aiosqlite

from ..paths import get_data_dir

logger = logging.getLogger(__name__)

# 多轮上下文窗口（功能清单 4.4）：取最近 N 条消息拼装历史，先保"截断不报错"。
HISTORY_LIMIT = 20

DB_FILENAME = "mochi.db"

# 版本号 → DDL 列表。新增表/字段请追加更高版本号，勿改历史条目。
_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE sessions (
            id         TEXT PRIMARY KEY,
            title      TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            ts         INTEGER NOT NULL
        )
        """,
        "CREATE INDEX idx_messages_session_ts ON messages(session_id, ts)",
    ],
}

# 会话标题取自首条用户消息的前 N 个字符。
_TITLE_MAX_CHARS = 30


def get_store_path() -> Path:
    """会话库落盘位置：数据目录（与 Tauri app_data_dir 对齐）下的 mochi.db。"""
    return get_data_dir() / DB_FILENAME


def _now_ms() -> int:
    return int(time.time() * 1000)


class SessionStore:
    """会话与消息的持久化读写。线程/协程安全（内部单锁串行化）。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    # -- 生命周期 -----------------------------------------------------------

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    def _resolve_path(self) -> Path:
        if self._db_path is not None:
            return self._db_path
        return get_store_path()

    async def _open(self) -> aiosqlite.Connection:
        """懒打开：首次访问才连接并执行迁移。调用方需已持锁。"""
        if self._conn is None:
            path = self._resolve_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            await self._migrate(conn)
            self._conn = conn
        return self._conn

    @staticmethod
    async def _migrate(conn: aiosqlite.Connection) -> None:
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        cursor = await conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        row = await cursor.fetchone()
        current = row[0] if row else 0
        for version in sorted(_MIGRATIONS):
            if version > current:
                for ddl in _MIGRATIONS[version]:
                    await conn.execute(ddl)
                await conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                logger.info("会话库迁移到 schema v%s", version)
        await conn.commit()

    # -- 写 -----------------------------------------------------------------

    async def append_message(self, session_id: str, role: str, content: str) -> None:
        """落盘一条消息；会话不存在则自动创建（首条用户消息作为标题）。"""
        async with self._lock:
            conn = await self._open()
            now = _now_ms()
            await conn.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) "
                "VALUES (?, NULL, ?, ?) ON CONFLICT(id) DO NOTHING",
                (session_id, now, now),
            )
            if role == "user":
                # 首次出现用户消息时回填标题（title 为 NULL 才写）
                await conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ? AND title IS NULL",
                    (content[:_TITLE_MAX_CHARS], session_id),
                )
            await conn.execute(
                "INSERT INTO messages (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            await conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            await conn.commit()

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及其全部消息；返回是否确实删除了内容。"""
        async with self._lock:
            conn = await self._open()
            cursor = await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            await conn.commit()
            return cursor.rowcount > 0

    # -- 读 -----------------------------------------------------------------

    async def recent_messages(self, session_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
        """最近 N 条消息（时间正序），供多轮上下文拼装。"""
        async with self._lock:
            conn = await self._open()
            cursor = await conn.execute(
                "SELECT role, content, ts FROM messages WHERE session_id = ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (session_id, limit),
            )
            rows = await cursor.fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in reversed(rows)]

    async def get_messages(self, session_id: str) -> list[dict]:
        """会话全部消息（时间正序），供历史回看。"""
        async with self._lock:
            conn = await self._open()
            cursor = await conn.execute(
                "SELECT role, content, ts FROM messages WHERE session_id = ? "
                "ORDER BY ts ASC, id ASC",
                (session_id,),
            )
            rows = await cursor.fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows]

    async def list_sessions(self) -> list[dict]:
        """全部会话（按最近活跃倒序），供前端历史列表。"""
        async with self._lock:
            conn = await self._open()
            cursor = await conn.execute(
                "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
            )
            rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
            }
            for r in rows
        ]
