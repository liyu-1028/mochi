"""内置工具集（M1-S4 任务 9，ADR-0008 D5）：最小可演示工具对。

设计目标：让 ReAct 循环与危险确认流在真实产品里端到端可演示——
- ``get_current_time``（safe）：无副作用，演示直通执行；
- ``read_text_file``（dangerous）：读用户文件属隐私敏感操作（内容将进入
  模型上下文），演示 6.5 确认框 + 「总是允许」白名单。

护栏（6.5/6.7）：
- 尺寸上限 256KB：超出仅返回前缀并注明截断，不整读大文件进内存；
- 二进制探测：首块含 NUL 字节或 UTF-8 解码失败即拒绝，错误文案可读；
- 语义异常（文件不存在/目录/二进制）抛出，由 ToolRegistry.execute 统一
  收敛为 ``ToolExecution(ok=False)`` 回灌模型自纠（本模块不外抛到回合层）。

扩展口径：6.8–6.10 内置技能包（P1/M2）沿 ToolSpec 继续追加，注册表不动。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .registry import DangerLevel, ToolRegistry, ToolSpec

#: 文本读取上限（字节）：演示级上限，防止大文件挤爆上下文
_MAX_FILE_BYTES = 256 * 1024

_WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")


class CurrentTimeArgs(BaseModel):
    tz_offset_minutes: int = Field(
        default=0,
        ge=-720,
        le=840,
        description="目标时区相对 UTC 的偏移分钟数（如北京时间 +480）；默认 0 = UTC",
    )


class _ReadTextFileArgs(BaseModel):
    path: str = Field(description="要读取的文件路径（绝对路径或 ~ 开头）")


async def _current_time(args: dict[str, Any]) -> str:
    offset = args.get("tz_offset_minutes", 0)
    tz = timezone(timedelta(minutes=offset))
    now = datetime.now(tz)
    sign = "+" if offset >= 0 else "-"
    hh, mm = divmod(abs(offset), 60)
    return (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{_WEEKDAYS[now.weekday()]}"
        f" UTC{sign}{hh:02d}:{mm:02d}"
    )


async def _read_text_file(args: dict[str, Any]) -> str:
    path = Path(args["path"]).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    if not path.is_file():
        raise ValueError(f"不是普通文件（可能是目录或链接）：{path}")

    size = path.stat().st_size
    with path.open("rb") as f:
        data = f.read(_MAX_FILE_BYTES)

    if b"\x00" in data[:8192]:
        raise ValueError(f"疑似二进制文件，仅支持 UTF-8 文本：{path}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"非 UTF-8 文本或二进制文件，无法读取：{path}") from exc

    note = ""
    if size > _MAX_FILE_BYTES:
        note = f"\n\n（文件共 {size} 字节，超出上限，仅返回前 {_MAX_FILE_BYTES} 字节）"
    return text + note


#: 内置工具清单：顺序即注册顺序（list_specs 消费方依赖稳定序）
BUILTIN_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_current_time",
        description=(
            "获取当前日期和时间（含星期与时区）。当用户询问时间、日期、星期，"
            "或你需要计算相对时间（如「30 分钟后」）时调用。"
        ),
        args_schema=CurrentTimeArgs,
        executor=_current_time,
        danger=DangerLevel.SAFE,
    ),
    ToolSpec(
        name="read_text_file",
        description=(
            "读取本机一个 UTF-8 文本文件的内容（上限 256KB，超出截断；"
            "二进制文件会被拒绝）。读取用户文件涉及隐私，需用户确认。"
        ),
        args_schema=_ReadTextFileArgs,
        executor=_read_text_file,
        danger=DangerLevel.DANGEROUS,
    ),
]


def register_builtin_tools(registry: ToolRegistry) -> list[ToolSpec]:
    """将内置工具注册进注册表；返回本次注册的工具清单。

    幂等性：不幂等（重名抛 ToolRegistryError）——重复装配属启动期错误，
    应尽早暴露而非静默吞并（对齐 register 既有语义）。
    """
    for spec in BUILTIN_TOOLS:
        registry.register(spec)
    return list(BUILTIN_TOOLS)
