"""本地持久化层（M1-S1）：会话与消息落盘，多轮上下文的事实源。

规范约束（docs/internal/research/specifications-research.md A5）：
- SQLite + 显式 migration，首张表即立规矩（为 S4 memories 表铺路）；
- 全本地存储，不上传（功能清单 6.4 隐私红线）。
"""

from .database import HISTORY_LIMIT, SessionStore, get_store_path

__all__ = ["HISTORY_LIMIT", "SessionStore", "get_store_path"]
