"""failback 核心层 —— 零依赖。"""

from failback.core.context import (
    ContextBuilder,
    DefaultContextBuilder,
    PlaywrightContextBuilder,
)
from failback.core.decorator import with_recovery
from failback.core.exceptions import RepairFailedException
from failback.core.handler import ExceptionHandler, handle_exception
from failback.core.registry import SolutionRegistry
from failback.core.solution import FailBackSolution

__all__ = [
    "ContextBuilder",
    "DefaultContextBuilder",
    "PlaywrightContextBuilder",
    "with_recovery",
    "RepairFailedException",
    "ExceptionHandler",
    "handle_exception",
    "SolutionRegistry",
    "FailBackSolution",
]
