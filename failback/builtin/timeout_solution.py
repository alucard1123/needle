"""内置 timeout 修复策略。

针对 :class:`~failback.core.context.PlaywrightContextBuilder` 识别出的环境型超时
（上下文带 ``timeout_status``）做对应处理。
"""

import logging

from failback.core.solution import FailBackSolution

logger = logging.getLogger(__name__)


class TimeoutSolution(FailBackSolution):
    """根据 ``timeout_status`` 选择不同的超时恢复手段。"""

    PRIORITY = 50

    def can_fix(self) -> bool:
        return self.context.get("timeout_status", 0) > 0

    def fix(self) -> bool:
        status = self.context.get("timeout_status", 0)
        page = self.context.get("page")
        match status:
            case 1:
                # 页面有 waiting 字样：再等等，然后重试。
                return self._handle_waiting(page)
            case 2:
                # Validation error has occurred 页面：暂未实现具体动作。
                logger.warning("检测到 Validation error 页面，暂无自动恢复手段")
                return False
            case 3:
                # 页面点了不动：暂未实现具体动作。
                logger.warning("页面无响应，暂无自动恢复手段")
                return False
        return False

    def _handle_waiting(self, page) -> bool:
        """等待页面加载完成后重试失败的操作。"""
        try:
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            execution = self.context.get("execution")
            if execution:
                eval(execution)  # noqa: S307 - execution 来自受控的异常栈解析
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("等待后重试仍失败：%s", e)
            return False
