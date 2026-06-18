"""with_recovery —— 把自动修复能力以装饰器形式注入到任意函数（核心零依赖）。

适合包装二次封装后的页面操作方法：函数抛异常时自动尝试修复，修复成功可返回
修复结果，失败按配置决定是否重新抛出。

用法::

    from failback import with_recovery

    @with_recovery(
        context_extractor=lambda page, locator, **kw: {
            "page": page,
            "locator": locator,
            **kw,
        }
    )
    def click_element(page, locator):
        page.locator(locator).click()
"""

from typing import Callable, Optional
import logging

from failback.core.exceptions import RepairFailedException

logger = logging.getLogger(__name__)


def with_recovery(
    *,
    context_extractor: Optional[Callable] = None,
    reraise_on_failure: bool = True,
):
    """装饰器工厂。

    :param context_extractor: 从被装饰函数的入参中提取修复上下文的可调用对象，
        接收与被装饰函数相同的 ``*args/**kwargs``，返回上下文 dict。
        缺省时取 ``kwargs['context']``。
    :param reraise_on_failure: 修复失败时是否重新抛出 ``RepairFailedException``。
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 - 捕获后交给修复链处理
                if context_extractor:
                    context = context_extractor(*args, **kwargs)
                else:
                    context = kwargs.get("context", {})

                repair = RepairFailedException(
                    f"方法 {func.__name__} 执行失败：{e}",
                    context=context,
                    original_exception=e,
                )

                if repair.attempt_recovery():
                    logger.info("[%s] 修复成功：%s", func.__name__, repair.recovered_result)
                    return repair.recovered_result

                if reraise_on_failure:
                    raise repair
                return None

        wrapper.__wrapped__ = func
        wrapper.__name__ = getattr(func, "__name__", "wrapper")
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator
