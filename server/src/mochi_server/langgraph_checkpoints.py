"""langgraph checkpoint 装配（M1-S4，ADR-0008 D4）。

独立连接 + 独立文件 ``mochi-checkpoints.db``（同 get_data_dir）：
- 不破坏 SessionStore「单连接 + 全局锁」不变量（store/database.py 设计要点，
  多连接写同一库有 database is locked 风险）；
- checkpoint 数据可随时重建、无迁移负担，生命周期与对话历史不同，
  故不与 mochi.db 同库（D4 措辞据此修正，见 ADR-0008）。

thread_id 约定：run_id（非 session_id）——历史以 SessionStore 为唯一
事实源，避免 checkpoint 内消息与拼装历史双计（ADR-0008 D4）。
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .paths import get_data_dir

CHECKPOINT_DB_FILENAME = "mochi-checkpoints.db"


async def build_checkpointer(
    db_path: Path | None = None,
) -> tuple[aiosqlite.Connection, AsyncSqliteSaver]:
    """打开 checkpoint 库连接并建表；返回 (conn, saver)。

    调用方（main.py lifespan）负责在退出时 ``await conn.close()``。
    """
    conn = await aiosqlite.connect(db_path or get_data_dir() / CHECKPOINT_DB_FILENAME)
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return conn, saver
