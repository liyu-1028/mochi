#!/usr/bin/env python3
"""soak —— 挂机浸泡驱动（§8 稳定性：夜间 12h×6 分段，泄漏用斜率判定）。

按间隔向 sidecar 发 chat.send（轮换提示词模拟真实对话泵），每轮采样
进程树 RSS，输出 JSONL 轮次记录 + 期末摘要（RSS 斜率、错误计数）。

依赖：websockets（server dev 依赖已含）。用法：
  cd server && uv run python ../scripts/soak.py --minutes 720 --out soak-night1.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import websockets

PROMPTS = [
    "今天天气怎么样？",
    "帮我记一下：明天上午十点有个会。",
    "讲个冷笑话。",
    "我现在有点累。",
    "推荐一首适合工作时的纯音乐。",
    "帮我看看现在几点了。",
]


def envelope(cmd_type: str, data: dict) -> str:
    return json.dumps(
        {
            "v": "0.1",
            "type": cmd_type,
            "id": str(uuid.uuid4()),
            "ts": int(time.time() * 1000),
            "data": data,
        },
        ensure_ascii=False,
    )


def tree_rss_mb(pid: int) -> float:
    """复用 perf_report 的三路归集 + 一次采样求和。"""
    from perf_report import collect_target_pids, sample

    rows = sample(collect_target_pids(pid))
    return round(sum(r["rss_mb"] for r in rows), 1)


def find_desktop_pid() -> int | None:
    import subprocess

    out = subprocess.run(["ps", "-axo", "pid,comm"], capture_output=True, text=True).stdout
    for line in out.splitlines()[1:]:
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and "mochi-desktop" in parts[1]:
            return int(parts[0])
    return None


def slope_mb_per_hour(rss: list[float], interval_s: float) -> float:
    n = len(rss)
    if n < 3:
        return 0.0
    xs = [i * interval_s / 3600.0 for i in range(n)]
    mx, my = sum(xs) / n, sum(rss) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, rss)) / denom


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=120.0, help="每轮对话间隔（秒）")
    parser.add_argument("--url", default="ws://127.0.0.1:8199/ws")
    parser.add_argument("--out", type=Path, default=Path("soak.jsonl"))
    args = parser.parse_args()

    pid = find_desktop_pid()
    if pid is None:
        print("未找到 mochi-desktop 进程")
        return 1

    deadline = time.monotonic() + args.minutes * 60
    round_no, errors, timeouts = 0, 0, 0
    rss_samples: list[float] = []
    session_id = f"soak-{uuid.uuid4().hex[:8]}"

    async with websockets.connect(args.url, max_size=2**22) as ws:
        await ws.send(
            envelope("hello", {"versions": ["0.1"], "client": {"name": "soak", "version": "0"}})
        )
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert ack["type"] == "hello_ack", ack

        while time.monotonic() < deadline:
            round_no += 1
            run_id = f"soak-run-{round_no}"
            text = PROMPTS[(round_no - 1) % len(PROMPTS)]
            started = time.monotonic()
            status, reply_len = "ok", 0
            try:
                await ws.send(
                    envelope(
                        "chat.send",
                        {"runId": run_id, "sessionId": session_id, "text": text},
                    )
                )
                # 收事件直到 run 终态（complete/cancelled/error）
                while True:
                    frame = json.loads(
                        await asyncio.wait_for(ws.recv(), timeout=180.0)
                    )
                    ftype = frame.get("type", "")
                    if ftype == "text.delta":
                        reply_len += len(frame["data"].get("delta", ""))
                    if ftype == "run.error":
                        status, errors = "error", errors + 1
                    if ftype in ("run.finished", "run.error", "run.cancelled"):
                        break
            except asyncio.TimeoutError:
                status, timeouts = "timeout", timeouts + 1
            except Exception as exc:  # 连接层异常：重连下一轮
                status, errors = "error", errors + 1
                print(f"round {round_no} 异常：{exc}")
                try:
                    await ws.close()
                except Exception:
                    pass
                # 重连（跳出 while 逻辑保持简单：soak 容忍进程内中断）
                break

            elapsed = round(time.monotonic() - started, 1)
            rss = tree_rss_mb(pid)
            rss_samples.append(rss)
            record = {
                "round": round_no,
                "status": status,
                "reply_len": reply_len,
                "elapsed_s": elapsed,
                "rss_mb": round(rss, 1),
            }
            with open(args.out, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(json.dumps(record, ensure_ascii=False), flush=True)
            await asyncio.sleep(args.interval)

    slope = slope_mb_per_hour(rss_samples, args.interval)
    summary = {
        "rounds": round_no,
        "errors": errors,
        "timeouts": timeouts,
        "rss_start_mb": round(rss_samples[0], 1) if rss_samples else None,
        "rss_end_mb": round(rss_samples[-1], 1) if rss_samples else None,
        "rss_slope_mb_per_hour": round(slope, 2),
    }
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    with open(args.out, "a", encoding="utf-8") as f:
        f.write(json.dumps({"summary": summary}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
