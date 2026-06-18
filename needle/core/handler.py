"""ExceptionHandler —— 库的统一入口（核心零依赖）。

典型用法::

    from needle import ExceptionHandler

    try:
        page.get_by_role("button", name="SEARCH").click()
    except Exception as e:
        ExceptionHandler(page=page).handle_exception(e)

``handle_exception(e)`` 会：构建上下文 → 创建 :class:`RepairFailedException`
→ 调用 ``attempt_recovery()`` 沿责任链查找并执行可用的 ``NeedleSolution``。
修复成功则记录日志正常返回；全部失败则抛出 ``RepairFailedException``。
"""

from typing import Optional
import logging

from needle.core.context import ContextBuilder, PlaywrightContextBuilder
from needle.core.exceptions import RepairFailedException

logger = logging.getLogger(__name__)


class ExceptionHandler:
    """异常处理入口，把异常委派给修复责任链。

    :param page: 自动化测试的页面对象（如 Playwright Page），供上下文构建/修复使用。
    :param context_builder: 上下文构建器，默认 :class:`PlaywrightContextBuilder`。
    :param reraise_on_failure: 修复失败时是否抛出 ``RepairFailedException``（默认 True）。
    """

    def __init__(
        self,
        page=None,
        context_builder: Optional[ContextBuilder] = None,
        reraise_on_failure: bool = True,
    ):
        self.page = page
        self.context_builder = context_builder or PlaywrightContextBuilder()
        self.reraise_on_failure = reraise_on_failure

    def handle_exception(self, exception: Exception, **context_kwargs) -> bool:
        """处理异常：构建上下文 → 尝试修复。返回是否修复成功。

        额外的关键字参数会透传给 context builder，便于补充上下文（如 ``locator=...``）。
        """
        context = self.context_builder.build(exception, page=self.page, **context_kwargs)

        repair = RepairFailedException(
            f"处理异常时尝试自动修复：{exception}",
            context=context,
            original_exception=exception,
        )

        if repair.attempt_recovery():
            logger.info("修复成功：%s", repair.recovered_result)
            return True

        if self.reraise_on_failure:
            raise repair
        logger.warning("修复失败，且配置为不重新抛出异常")
        return False


def handle_exception(
    exception: Exception,
    *,
    page=None,
    context_builder: Optional[ContextBuilder] = None,
    reraise_on_failure: bool = True,
    **context_kwargs,
) -> bool:
    """模块级便捷函数，等价于 ``ExceptionHandler(...).handle_exception(exception)``。"""
    return ExceptionHandler(
        page=page,
        context_builder=context_builder,
        reraise_on_failure=reraise_on_failure,
    ).handle_exception(exception, **context_kwargs)
