"""failback —— 自动化测试异常自愈库。

捕获到异常时调用 ``ExceptionHandler(...).handle_exception(e)``，由责任链查找可用的
``FailBackSolution`` 并尝试修复。内置 cache/image/prompt 三种 locator 修复策略；
用户继承 ``FailBackSolution`` 实现 ``can_fix`` / ``fix`` 并 ``register_solution`` 即可扩展。

核心（handler/registry/基类/异常/装饰器）零依赖；内置策略的重依赖按 extras 安装。
"""

from failback.core import (
    ContextBuilder,
    DefaultContextBuilder,
    ExceptionHandler,
    FailBackSolution,
    PlaywrightContextBuilder,
    RepairFailedException,
    SolutionRegistry,
    handle_exception,
    with_recovery,
)

#: 注册自定义/内置策略的便捷别名。
register_solution = SolutionRegistry.register

__version__ = "0.1.0"

__all__ = [
    "ContextBuilder",
    "DefaultContextBuilder",
    "PlaywrightContextBuilder",
    "ExceptionHandler",
    "handle_exception",
    "FailBackSolution",
    "RepairFailedException",
    "SolutionRegistry",
    "register_solution",
    "with_recovery",
    "__version__",
]
