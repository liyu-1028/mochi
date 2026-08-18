"""ToolPolicy —— dangerous 工具的「总是允许」白名单（M1-S4，功能清单 6.5）。

读写经回调注入（``load``/``save``），不绑死 config 层：生产路径由
ProviderRegistry 提供（读内存 config、写盘走 save_config + update_config 热生效，
沿 config_routes._apply 惯例）；测试注入闭包容器。load 每次实调——同一 policy
实例在配置热切换后读到最新值（闭包捕获 registry 自身）。

语义边界：协议只定义「总是允许」（tool.confirm 的 remember=true）；
deny 不记忆——每次危险调用都重新询问。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class ToolPolicy:
    def __init__(
        self,
        *,
        load: Callable[[], list[str]],
        save: Callable[[list[str]], None],
    ) -> None:
        self._load = load
        self._save = save

    def is_allowed(self, name: str) -> bool:
        return name in self._load()

    def allow_always(self, name: str) -> None:
        """入白名单并持久化（幂等：已在名单则不动盘）。"""
        current = self._load()
        if name in current:
            return
        current.append(name)
        self._save(current)
        logger.info("工具 %s 已加入「总是允许」白名单", name)
