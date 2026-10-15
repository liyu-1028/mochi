"""TTS 合成缓存：进程内 LRU + TTL。

云端按字符计费：TTL 放宽到 1 小时（会话内同文本直接回放，不重复付费）；
volume 已前移为前端播放增益，不再进入缓存键（调音量不使缓存失效）。
"""

from __future__ import annotations

import time
from collections import OrderedDict


class TTSCache:
    def __init__(self, max_items: int | None = None, ttl_seconds: float | None = None) -> None:
        self._max_items = max_items if max_items is not None else _MAX_ITEMS
        self._ttl = ttl_seconds if ttl_seconds is not None else _TTL_SECONDS
        self._store: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()

    def get(self, key: str) -> tuple[bytes, str] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        at, audio, engine = entry
        if time.monotonic() - at > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return audio, engine

    def put(self, key: str, audio: bytes, engine: str) -> None:
        self._store[key] = (time.monotonic(), audio, engine)
        self._store.move_to_end(key)
        while len(self._store) > self._max_items:
            self._store.popitem(last=False)


#: LRU 条数上限（mp3 整段缓存，50 条内存量级可控）
_MAX_ITEMS = 50
#: TTL：1 小时（云端计费，会话内回放不重复付费）
_TTL_SECONDS = 3600.0

CACHE = TTSCache()


def make_key(text: str, voice_id: str, rate: float) -> str:
    return f"{rate:.2f}|{voice_id}|{text}"
