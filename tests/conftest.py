import pytest

from failback.core.registry import SolutionRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个测试前后清空全局注册表，避免相互污染。"""
    saved = SolutionRegistry.registered()
    SolutionRegistry.clear()
    yield
    SolutionRegistry.clear()
    for c in saved:
        SolutionRegistry.register(c)


class FakeError(Exception):
    """模拟 Playwright 风格异常：带 message / stack 属性。"""

    def __init__(self, message="", stack=""):
        super().__init__(message)
        self.message = message
        self.stack = stack
