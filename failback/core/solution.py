"""FailBackSolution —— 修复策略基类（零依赖）。

用户扩展契约：继承 ``FailBackSolution`` 并实现 ``can_fix`` / ``fix`` 两个方法，
再通过 :func:`failback.register_solution` 注册即可被自动发现并纳入责任链。
"""

from abc import ABC, abstractmethod
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class FailBackSolution(ABC):
    """异常修复策略基类，封装责任链公共逻辑。

    子类通过类属性 ``PRIORITY`` 声明优先级（数字越小越先尝试），
    并实现 :meth:`can_fix` 判定是否能处理当前上下文、:meth:`fix` 执行实际修复。
    """

    #: 优先级，数字越小越先被尝试。
    PRIORITY: int = 100

    def __init__(self, context: dict):
        self.context = context
        self._next_solution: Optional["FailBackSolution"] = None

    @abstractmethod
    def can_fix(self) -> bool:
        """判断当前异常上下文是否可以被本 solution 处理。"""
        raise NotImplementedError

    @abstractmethod
    def fix(self) -> bool:
        """执行修复逻辑，返回是否修复成功。子类必须实现。"""
        raise NotImplementedError

    def set_next(self, solution: "FailBackSolution") -> "FailBackSolution":
        """设置责任链上的下一个修复方案，返回该方案以便链式调用。"""
        self._next_solution = solution
        return solution

    def execute_next(self, context: dict) -> bool:
        """把上下文交给责任链上的下一个修复方案。"""
        if self._next_solution:
            return self._next_solution.handle(context)
        return False

    def handle(self, context: dict) -> bool:
        """责任链入口：先尝试自己修复，修不了再交给下一个。"""
        if self.can_fix():
            logger.info("[%s] 申请出战...", self.__class__.__name__)
            try:
                if self.fix():
                    logger.info("[%s] 修复成功", self.__class__.__name__)
                    return True
                logger.warning("[%s] 歇菜，下一个", self.__class__.__name__)
            except Exception as e:  # noqa: BLE001 - 单个策略失败不应中断责任链
                logger.error("[%s] 修复过程中遇到异常：%s", self.__class__.__name__, e)
        return self.execute_next(context)
