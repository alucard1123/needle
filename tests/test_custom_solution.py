"""扩展契约：用户自定义 NeedleSolution 能被注册、发现并命中。"""

from needle import NeedleSolution, register_solution
from needle.core.registry import SolutionRegistry
from needle.core.exceptions import RepairFailedException


def test_custom_solution_via_decorator_is_discovered_and_used():
    @register_solution
    class MyRetry(NeedleSolution):
        PRIORITY = 5

        def can_fix(self):
            return "locator" in self.context

        def fix(self):
            self.context["fixed_element"] = "retried:" + self.context["locator"]
            return True

    assert MyRetry in SolutionRegistry.registered()

    repair = RepairFailedException(context={"locator": "save-btn"})
    assert repair.attempt_recovery() is True
    assert repair.recovered_result == "retried:save-btn"


def test_custom_priority_beats_lower_priority():
    order = []

    @register_solution
    class Low(NeedleSolution):
        PRIORITY = 100

        def can_fix(self):
            order.append("low")
            return True

        def fix(self):
            return False

    @register_solution
    class High(NeedleSolution):
        PRIORITY = 1

        def can_fix(self):
            order.append("high")
            return True

        def fix(self):
            return False

    RepairFailedException(context={"x": 1}).attempt_recovery()
    assert order == ["high", "low"]  # 先 PRIORITY=1，再 PRIORITY=100
