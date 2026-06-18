"""failback 内置策略（可选件，重依赖按需安装）。

``register_builtins()`` 把全部内置策略注册到 :class:`SolutionRegistry`，
也可只 import 需要的策略类自行注册。
"""

from failback.builtin.backends import (
    AIClient,
    CacheBackend,
    ImageMatcher,
    OpenCVImageMatcher,
    PickleDBCacheBackend,
)
from failback.builtin.kimi_client import KimiClient
from failback.builtin.locator_solutions import (
    ByCacheSolution,
    ByImageSolution,
    ByPromptSolution,
)
from failback.builtin.timeout_solution import TimeoutSolution
from failback.core.registry import SolutionRegistry

__all__ = [
    "AIClient",
    "CacheBackend",
    "ImageMatcher",
    "OpenCVImageMatcher",
    "PickleDBCacheBackend",
    "KimiClient",
    "ByCacheSolution",
    "ByImageSolution",
    "ByPromptSolution",
    "TimeoutSolution",
    "register_builtins",
]


def register_builtins() -> None:
    """注册全部内置策略到全局 SolutionRegistry。"""
    for sol in (ByCacheSolution, ByImageSolution, ByPromptSolution, TimeoutSolution):
        SolutionRegistry.register(sol)
