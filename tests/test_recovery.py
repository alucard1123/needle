"""责任链与 attempt_recovery 的成功/失败两路。"""

from failback.core.exceptions import RepairFailedException
from failback.core.registry import SolutionRegistry
from failback.core.solution import FailBackSolution


class CannotFix(FailBackSolution):
    PRIORITY = 10
    handled = False

    def can_fix(self):
        return False

    def fix(self):  # 不应被调用
        CannotFix.handled = True
        return True


class FixesIt(FailBackSolution):
    PRIORITY = 20

    def can_fix(self):
        return "locator" in self.context

    def fix(self):
        self.context["fixed_element"] = "fixed-" + self.context["locator"]
        return True


class AlwaysFails(FailBackSolution):
    PRIORITY = 30

    def can_fix(self):
        return True

    def fix(self):
        return False


def test_chain_skips_cannot_fix_then_fixes():
    CannotFix.handled = False
    SolutionRegistry.register(CannotFix)
    SolutionRegistry.register(FixesIt)
    repair = RepairFailedException(context={"locator": "btn"})
    assert repair.attempt_recovery() is True
    assert repair.recovered is True
    assert repair.recovered_result == "fixed-btn"
    assert CannotFix.handled is False  # can_fix=False 的 fix 不会被调用


def test_attempt_recovery_all_fail():
    SolutionRegistry.register(AlwaysFails)
    repair = RepairFailedException(context={"locator": "btn"})
    assert repair.attempt_recovery() is False
    assert repair.recovered is False


def test_attempt_recovery_no_context():
    repair = RepairFailedException(context=None)
    assert repair.attempt_recovery() is False


def test_attempt_recovery_no_solutions():
    repair = RepairFailedException(context={"locator": "btn"})
    assert repair.attempt_recovery() is False  # 注册表为空


def test_solution_fix_exception_does_not_break_chain():
    class Boom(FailBackSolution):
        PRIORITY = 5

        def can_fix(self):
            return True

        def fix(self):
            raise ValueError("boom")

    SolutionRegistry.register(Boom)
    SolutionRegistry.register(FixesIt)
    repair = RepairFailedException(context={"locator": "btn"})
    assert repair.attempt_recovery() is True  # Boom 抛异常后继续到 FixesIt


def test_original_exception_preserved_as_cause():
    original = ValueError("root")
    repair = RepairFailedException(context={}, original_exception=original)
    assert repair.original_exception is original
    assert repair.__cause__ is original
