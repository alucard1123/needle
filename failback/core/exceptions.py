"""RepairFailedException —— 修复失败异常 & 修复入口（零依赖）。

``handle_exception`` 在构建好上下文后会创建本异常并调用 :meth:`attempt_recovery`，
由它驱动 :class:`~failback.core.registry.SolutionRegistry` 组装责任链并尝试修复。
修复成功返回 ``True``；若所有策略都无能为力，本异常会被原样抛出，且通过
``__cause__`` 保留原始异常以便排错。
"""

from typing import Optional
import logging

from failback.core.registry import SolutionRegistry

logger = logging.getLogger(__name__)


class RepairFailedException(Exception):
    """表示「自动修复失败」的异常，同时承载修复尝试的入口逻辑。"""

    def __init__(
        self,
        message: str = "自动修复失败",
        *,
        context: Optional[dict] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.context = context or {}
        self.original_exception = original_exception
        self.recovered = False
        self.recovered_result = None
        # 保留原始异常链，便于追溯根因。
        if original_exception is not None:
            self.__cause__ = original_exception

    def attempt_recovery(self) -> bool:
        """组装责任链并尝试修复，返回是否成功。"""
        if not self.context:
            logger.warning("无上下文信息，无法执行修复策略")
            return False

        chain = SolutionRegistry.create_chain(self.context)
        if chain is None:
            logger.warning("没有可用的修复策略（SolutionRegistry 为空）")
            return False

        self.recovered = chain.handle(self.context)
        if self.recovered:
            self.recovered_result = self.context.get("fixed_element")
        return self.recovered
