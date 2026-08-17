"""工具注册表（M1-S4，ADR-0008 D5）：功能清单 6.5 工具调用框架的地基。

双轨原则：
- **声明轨**：``langchain_tools()`` 产出 StructuredTool 列表，仅供
  ``bind_tools`` 向模型声明（任务 5 图内核消费）；
- **执行轨**：``execute(name, args)`` 是唯一执行入口——参数校验、异常
  收敛、日志均在此收口；任务 7 的危险确认（6.5）在调用 ``spec.executor``
  前插入。LC 工具的 coroutine 只是转调 execute，不存在第二条执行路径。

danger 分级（6.5）：safe 直接执行；dangerous（写删文件、外发类）须经
用户确认 +「总是允许」白名单——确认机制属任务 7，本模块只携带分级。
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

#: 模型侧工具标识符：小写开头，小写数字下划线，≤64（fs.list_dir 形态）
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DESCRIPTION_MAX = 1024


class DangerLevel(StrEnum):
    """危险分级：决定执行前是否需要用户确认（任务 7 消费）。"""

    SAFE = "safe"  # 只读/无副作用
    DANGEROUS = "dangerous"  # 写删/外发，须确认（6.5）


class ToolRegistryError(ValueError):
    """注册期校验失败（name 非法/重复、schema/executor 不合规等）。"""


@dataclass(frozen=True)
class ToolSpec:
    """单个工具的完整声明（内容不是协议，留在服务端域内）。"""

    name: str
    description: str  # 模型据此决策是否调用，须写清用途与边界
    args_schema: type[BaseModel]  # pydantic v2，JSON schema 之源
    executor: Callable[[dict[str, Any]], Awaitable[str]]  # 单参 dict，返回文本
    danger: DangerLevel = DangerLevel.SAFE


@dataclass(frozen=True)
class ToolExecution:
    """execute 的统一结果：成功输出或可读失败原因（6.7 文案要求）。"""

    ok: bool
    output: str
    error_code: str | None = None  # unknown_tool | invalid_args | execution_error


class ToolRegistry:
    """工具注册与执行收口。生命周期：sidecar 进程级实例，任务 9 挂内置工具。"""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    # -- 注册 ----------------------------------------------------------------

    def register(self, spec: ToolSpec) -> None:
        """校验并注册；不合规抛 ToolRegistryError（启动期暴露配置错误）。"""
        if not _NAME_PATTERN.match(spec.name):
            raise ToolRegistryError(f"工具名 {spec.name!r} 不合规：需匹配 {_NAME_PATTERN.pattern}")
        if spec.name in self._specs:
            raise ToolRegistryError(f"工具名重复注册：{spec.name}")
        if not spec.description.strip() or len(spec.description) > _DESCRIPTION_MAX:
            raise ToolRegistryError(
                f"工具 {spec.name} 的 description 须非空且 ≤{_DESCRIPTION_MAX} 字"
            )
        if not (inspect.isclass(spec.args_schema) and issubclass(spec.args_schema, BaseModel)):
            raise ToolRegistryError(f"工具 {spec.name} 的 args_schema 须为 pydantic BaseModel 子类")
        if not inspect.iscoroutinefunction(spec.executor):
            raise ToolRegistryError(f"工具 {spec.name} 的 executor 须为 async 函数")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    # -- 声明轨（bind_tools 入参） -------------------------------------------

    def langchain_tools(self) -> list[StructuredTool]:
        """按需构建 LC 工具列表（不缓存；注册表低频变更，构建廉价）。

        coroutine 转调 execute（kwargs→dict 适配：LC 以字段名展开传参，
        实测 2026-08-18）；``func=None`` 意味着同步 invoke 不可用，仅异步
        路径。声明轨不设 danger——分级只影响执行轨。
        """
        return [
            StructuredTool(
                name=spec.name,
                description=spec.description,
                args_schema=spec.args_schema,
                func=None,
                coroutine=self._declare_coroutine(spec.name),
            )
            for spec in self._specs.values()
        ]

    def _declare_coroutine(self, name: str) -> Callable[..., Awaitable[ToolExecution]]:
        async def _run(**kwargs: Any) -> ToolExecution:
            return await self.execute(name, kwargs)

        return _run

    # -- 执行轨（唯一执行入口） ----------------------------------------------

    async def execute(self, name: str, args: dict[str, Any]) -> ToolExecution:
        """执行工具并收敛一切异常为 ToolExecution（不外抛，对齐 6.7）。"""
        spec = self._specs.get(name)
        if spec is None:
            return ToolExecution(ok=False, output=f"未知工具：{name}", error_code="unknown_tool")

        try:
            validated = spec.args_schema.model_validate(args)
        except ValidationError as exc:
            detail = "；".join(
                f"{'.'.join(str(loc) for loc in e['loc']) or '参数'}：{e['msg']}"
                for e in exc.errors()
            )
            return ToolExecution(
                ok=False, output=f"工具 {name} 参数不合法：{detail}", error_code="invalid_args"
            )

        try:
            output = await spec.executor(validated.model_dump())
        except Exception as exc:  # 执行器异常收敛：不中断回合，结果回灌模型自纠
            logger.exception("工具执行失败：%s", name)
            return ToolExecution(
                ok=False,
                output=f"工具 {name} 执行失败：{exc}",
                error_code="execution_error",
            )
        return ToolExecution(ok=True, output=output)
