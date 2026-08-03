"""RunManager 会话管理测试：生命周期包裹与取消路径。"""

from __future__ import annotations

import asyncio

import pytest

from mochi_server.agent import EchoAgentService, RunManager
from mochi_server.events import ChatSendData


class FrameRecorder:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def __call__(self, frame: dict) -> None:
        self.frames.append(frame)


def _send_data(text: str = "你好") -> ChatSendData:
    return ChatSendData(run_id="r-1", session_id="s-1", text=text)


async def _wait_idle(manager: RunManager, timeout: float = 5) -> None:
    tasks = list(manager._runs.values())  # 测试内部断言，访问私有注册表
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout)


@pytest.mark.asyncio
async def test_run_lifecycle_frames() -> None:
    """正常回合：run.started 开头、run.finished(complete) 结尾。"""
    recorder = FrameRecorder()
    manager = RunManager(EchoAgentService(chunk_delay=0, thinking_delay=0), recorder)

    await manager.start_run(_send_data())
    await _wait_idle(manager)

    types = [f["type"] for f in recorder.frames]
    assert types[0] == "run.started"
    assert types[-1] == "run.finished"
    assert recorder.frames[-1]["data"]["reason"] == "complete"
    assert "text.start" in types and "text.end" in types


@pytest.mark.asyncio
async def test_cancel_run() -> None:
    """取消路径：chat.cancel → run.finished(cancelled)。"""
    recorder = FrameRecorder()
    manager = RunManager(EchoAgentService(chunk_delay=0.05, thinking_delay=0.05), recorder)

    await manager.start_run(_send_data())
    await asyncio.sleep(0.02)  # 让回合跑起来
    await manager.cancel_run("r-1")
    await _wait_idle(manager)

    types = [f["type"] for f in recorder.frames]
    assert types[0] == "run.started"
    assert types[-1] == "run.finished"
    assert recorder.frames[-1]["data"]["reason"] == "cancelled"


@pytest.mark.asyncio
async def test_duplicate_run_id_ignored() -> None:
    """重复 runId：第二个被忽略，不产生两套生命周期帧。"""
    recorder = FrameRecorder()
    manager = RunManager(EchoAgentService(chunk_delay=0.02, thinking_delay=0.02), recorder)

    await manager.start_run(_send_data())
    await manager.start_run(_send_data())  # 重复
    await _wait_idle(manager)

    started = [f for f in recorder.frames if f["type"] == "run.started"]
    assert len(started) == 1


@pytest.mark.asyncio
async def test_cancel_unknown_run_is_noop() -> None:
    recorder = FrameRecorder()
    manager = RunManager(EchoAgentService(chunk_delay=0, thinking_delay=0), recorder)
    await manager.cancel_run("not-exists")
    assert recorder.frames == []
