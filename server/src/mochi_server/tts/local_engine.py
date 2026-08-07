"""本地 TTS 兜底引擎（零新依赖，保「离线也能出声」，音质次要）。

macOS：``say -o x.aiff -f 文本`` + ``afconvert`` 转 WAV；
Windows：PowerShell ``System.Speech`` 直出 WAV。
其余平台不支持 → TTSEngineError（降级链继续到纯文本）。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from . import TTSEngineError

ENGINE_NAME = "local"
MEDIA_TYPE = "audio/wav"

_TIMEOUT_S = 30
_MAC_BASE_WPM = 200  # say 默认语速经验值，rate=1.0 对齐


async def synthesize(text: str, rate: float) -> bytes:
    if sys.platform == "darwin":
        return await _mac_say(text, rate)
    if sys.platform.startswith("win"):
        return await _win_sapi(text, rate)
    raise TTSEngineError(f"平台 {sys.platform} 无本地 TTS 引擎")


async def _run(cmd: list[str], timeout: float = _TIMEOUT_S) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except (OSError, TimeoutError) as exc:
        raise TTSEngineError(f"本地引擎启动失败：{exc}") from exc
    if proc.returncode != 0:
        raise TTSEngineError(f"本地引擎退出码 {proc.returncode}：{err.decode()[:200]}")


async def _mac_say(text: str, rate: float) -> bytes:
    with tempfile.TemporaryDirectory(prefix="mochi-tts-") as tmp:
        txt = Path(tmp) / "in.txt"
        aiff = Path(tmp) / "out.aiff"
        wav = Path(tmp) / "out.wav"
        txt.write_text(text, encoding="utf-8")
        await _run(["say", "-r", str(int(_MAC_BASE_WPM * rate)), "-o", str(aiff), "-f", str(txt)])
        await _run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(aiff), str(wav)])
        try:
            return wav.read_bytes()
        except OSError as exc:
            raise TTSEngineError(f"本地引擎输出缺失：{exc}") from exc


async def _win_sapi(text: str, rate: float) -> bytes:
    # SAPI Rate 取值 -10..10，线性映射 rate 0.5..2.0
    sapi_rate = max(-10, min(10, round((rate - 1) * 10)))
    with tempfile.TemporaryDirectory(prefix="mochi-tts-") as tmp:
        txt = Path(tmp) / "in.txt"
        wav = Path(tmp) / "out.wav"
        txt.write_text(text, encoding="utf-8")
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.Rate = {sapi_rate};"
            f"$s.SetOutputToWaveFile('{wav}');"
            f"$s.Speak([System.IO.File]::ReadAllText('{txt}'));"
            "$s.Dispose()"
        )
        await _run(["powershell", "-NoProfile", "-Command", script])
        try:
            return wav.read_bytes()
        except OSError as exc:
            raise TTSEngineError(f"本地引擎输出缺失：{exc}") from exc


def supported() -> bool:
    return sys.platform == "darwin" or sys.platform.startswith("win")
