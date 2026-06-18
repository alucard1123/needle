"""needle 核心层 —— 零依赖。"""

from needle.core.context import (
    ContextBuilder,
    DefaultContextBuilder,
    PlaywrightContextBuilder,
)
from needle.core.decorator import with_recovery
from needle.core.exceptions import RepairFailedException
from needle.core.handler import ExceptionHandler, handle_exception
from needle.core.registry import SolutionRegistry
from needle.core.solution import NeedleSolution

__all__ = [
    "ContextBuilder",
    "DefaultContextBuilder",
    "PlaywrightContextBuilder",
    "with_recovery",
    "RepairFailedException",
    "ExceptionHandler",
    "handle_exception",
    "SolutionRegistry",
    "NeedleSolution",
]
