"""SolutionRegistry：注册、优先级排序、扫描、建链。"""

import pytest

from failback.core.registry import SolutionRegistry
from failback.core.solution import FailBackSolution


class A(FailBackSolution):
    PRIORITY = 30

    def can_fix(self):
        return True

    def fix(self):
        return True


class B(FailBackSolution):
    PRIORITY = 10

    def can_fix(self):
        return True

    def fix(self):
        return True


def test_register_sorts_by_priority():
    SolutionRegistry.register(A)
    SolutionRegistry.register(B)
    assert SolutionRegistry.registered() == [B, A]  # 10 在 30 前面


def test_register_is_idempotent():
    SolutionRegistry.register(A)
    SolutionRegistry.register(A)
    assert SolutionRegistry.registered() == [A]


def test_register_rejects_non_solution():
    with pytest.raises(TypeError):
        SolutionRegistry.register(int)
    with pytest.raises(TypeError):
        SolutionRegistry.register(FailBackSolution)


def test_create_chain_links_in_priority_order():
    SolutionRegistry.clear()
    SolutionRegistry.register(A)
    SolutionRegistry.register(B)
    head = SolutionRegistry.create_chain({}, include_builtins=False)
    assert isinstance(head, B)
    assert isinstance(head._next_solution, A)


def test_create_chain_empty_returns_none():
    SolutionRegistry.clear()
    assert SolutionRegistry.create_chain({}, include_builtins=False) is None


def test_create_chain_filter_func():
    SolutionRegistry.clear()
    SolutionRegistry.register(A)
    SolutionRegistry.register(B)
    head = SolutionRegistry.create_chain({}, filter_func=lambda c: c is A, include_builtins=False)
    assert isinstance(head, A)
    assert head._next_solution is None


def test_create_chain_includes_builtins():
    SolutionRegistry.clear()
    head = SolutionRegistry.create_chain({})
    assert head is not None
    names = {c.__name__ for c in SolutionRegistry.registered()}
    assert {"ByCacheSolution", "ByImageSolution", "ByPromptSolution", "TimeoutSolution"} <= names


def test_scan_discovers_builtin_package():
    found = SolutionRegistry.scan("failback.builtin", register=False)
    names = {c.__name__ for c in found}
    assert {"ByCacheSolution", "ByImageSolution", "ByPromptSolution", "TimeoutSolution"} <= names
