#!/usr/bin/env python3
"""perf_report —— 非功能基线采样（功能清单 §8，M1-S5 基线报告工具）。

仅用标准库（无 psutil 依赖）：经 `ps` 采样 mochi-desktop 进程树
（含 sidecar 子进程与 WKWebView 渲染进程）的 RSS/CPU，输出：

- 峰值/平均常驻内存（红线 ≤600MB）；
- 平均/峰值 CPU（空闲红线 ≤5%）；
- RSS 线性回归斜率（MB/h，泄漏判定用斜率而非绝对值——72h 挂机同理）；
- 逐进程明细 JSON + 人读摘要。

用法：
  python3 scripts/perf_report.py --duration 60            # 60s 采样
  python3 scripts/perf_report.py --pid 4824 --json out.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def find_desktop_pid() -> int | None:
    """找 mochi-desktop 主进程（dev: target/debug/mochi-desktop；release: app 包）。"""
    out = subprocess.run(
        ["ps", "-axo", "pid,comm"], capture_output=True, text=True
    ).stdout
    for line in out.splitlines()[1:]:
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and "mochi-desktop" in parts[1]:
            return int(parts[0])
    return None


def process_tree(pid: int) -> set[int]:
    """pid 及其全部后代（sidecar 子进程等）。"""
    out = subprocess.run(
        ["ps", "axo", "pid,ppid"], capture_output=True, text=True
    ).stdout
    parent_of: dict[int, int | None] = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2:
            parent_of[int(parts[0])] = int(parts[1])
    tree, frontier = {pid}, [pid]
    while frontier:
        current = frontier.pop()
        for child, parent in parent_of.items():
            if parent == current and child not in tree:
                tree.add(child)
                frontier.append(child)
    return tree


def collect_target_pids(pid: int) -> set[int]:
    """目标进程归集（三路）：
    1. 桌面主进程树（直属子进程）；
    2. 命令行匹配：sidecar（uv/uvicorn/mochi_server，中间 shell 退出后
       会被 reparent 到 launchd，树归集不全）；
    3. WebKit XPC（WebContent/Networking）：macOS 上父进程为 launchd，
       无可靠归属——用 pid 邻近启发式（应用启动时一同创建，文档已注明）。
    """
    targets = process_tree(pid)
    out = subprocess.run(
        ["ps", "axo", "pid,command"], capture_output=True, text=True
    ).stdout
    for line in out.splitlines()[1:]:
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        try:
            other = int(parts[0])
        except ValueError:
            continue
        cmd = parts[1]
        if "mochi_server" in cmd or ("uvicorn" in cmd and "mochi" in cmd):
            targets.add(other)
        elif "com.apple.WebKit.WebContent" in cmd or "com.apple.WebKit.Networking" in cmd:
            if abs(other - pid) <= 500:  # 启动邻近启发式（仅 macOS）
                targets.add(other)
    return targets


def sample(pids: set[int]) -> list[dict]:
    """一次采样：ps 拉全表，过滤进程树内 RSS/CPU。"""
    out = subprocess.run(
        ["ps", "-axo", "pid,ppid,%cpu,rss,comm"], capture_output=True, text=True
    ).stdout
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid = int(parts[0])
        if pid in pids:
            rows.append(
                {
                    "pid": pid,
                    "cpu": float(parts[2]),
                    "rss_mb": int(parts[3]) / 1024.0,
                    "comm": parts[4][:60],
                }
            )
    return rows


def linear_slope_mb_per_hour(samples: list[float], interval_s: float) -> float:
    """最小二乘斜率（MB/hour）；样本不足或方差过小返回 0。"""
    n = len(samples)
    if n < 3:
        return 0.0
    xs = [i * interval_s / 3600.0 for i in range(n)]
    mean_x = sum(xs) / n
    mean_y = sum(samples) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, samples)) / denom


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60.0, help="采样时长（秒）")
    parser.add_argument("--interval", type=float, default=2.0, help="采样间隔（秒）")
    parser.add_argument("--pid", type=int, default=None, help="mochi-desktop 主进程 pid")
    parser.add_argument("--json", type=Path, default=None, help="明细 JSON 输出路径")
    args = parser.parse_args()

    pid = args.pid or find_desktop_pid()
    if pid is None:
        print("未找到 mochi-desktop 进程（先启动应用）")
        return 1
    tree = collect_target_pids(pid)
    print(f"采样目标 pid={pid} 归集 {len(tree)} 个进程，时长 {args.duration}s")

    snapshots: list[list[dict]] = []
    totals: list[float] = []
    cpu_totals: list[float] = []
    deadline = time.monotonic() + args.duration
    while time.monotonic() < deadline:
        rows = sample(tree)
        if not rows:  # 进程退出
            print("目标进程已退出")
            break
        snapshots.append(rows)
        totals.append(sum(r["rss_mb"] for r in rows))
        cpu_totals.append(sum(r["cpu"] for r in rows))
        time.sleep(args.interval)

    if not totals:
        print("无有效样本")
        return 1

    slope = linear_slope_mb_per_hour(totals, args.interval)
    report = {
        "pid": pid,
        "process_count": len(tree),
        "samples": len(totals),
        "rss_mb": {
            "avg": round(sum(totals) / len(totals), 1),
            "peak": round(max(totals), 1),
            "slope_mb_per_hour": round(slope, 2),
        },
        "cpu_percent": {
            "avg": round(sum(cpu_totals) / len(cpu_totals), 1),
            "peak": round(max(cpu_totals), 1),
        },
        "thresholds": {"rss_mb": 600, "idle_cpu_percent": 5},
        "last_snapshot": snapshots[-1],
    }

    print(json.dumps({k: v for k, v in report.items() if k != "last_snapshot"}, indent=2))
    rss, cpu = report["rss_mb"], report["cpu_percent"]
    verdict = "PASS" if rss["peak"] <= 600 else "FAIL"
    print(f"\n内存红线 ≤600MB：峰值 {rss['peak']}MB → {verdict}")
    print(f"RSS 斜率：{rss['slope_mb_per_hour']} MB/h（斜率判泄漏，非绝对值）")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"明细已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
