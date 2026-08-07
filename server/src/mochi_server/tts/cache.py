"""TTS 合成结果缓存：文本+参数 hash 为键，避免重复网络合成（edge-tts 有往返开销）。

LRU 50 条 + TTL 10 分钟；进程内单实例（uvicorn 单事件循环，无锁足够）。
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict

_MAX_ITEMS = 50
_TTL_SECONDS = 600.0


def make_key(text: str, voice_id: str, rate: float, volume: float) -> str:
    payload = f"{text}|{voice_id}|{rate:.2f}|{volume:.2f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class TTSCache:
    """LRU+TTL 缓存：值带引擎名（命中回放仍如实上报 X-TTS-Engine）。"""

    def __init__(self, max_items: int = _MAX_ITEMS, ttl: float = _TTL_SECONDS) -> None:
        self._max_items = max_items
        self._ttl = ttl
        self._items: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()

    def get(self, key: str) -> tuple[bytes, str] | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        stamped_at, audio, engine = entry
        if time.monotonic() - stamped_at > self._ttl:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return audio, engine

    def put(self, key: str, audio: bytes, engine: str) -> None:
        self._items[key] = (time.monotonic(), audio, engine)
        self._items.move_to_end(key)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)


# 模块级单实例：路由层共用（测试可重置）
CACHE = TTSCache()
