"""ExceptionHandler + ContextBuilder：入口行为与 Playwright 解析（含降级、不再无限递归）。"""

import pytest

from needle.core.context import DefaultContextBuilder, PlaywrightContextBuilder
from needle.core.exceptions import RepairFailedException
from needle.core.handler import ExceptionHandler, handle_exception
from needle.core.registry import SolutionRegistry
from needle.core.solution import NeedleSolution

from conftest import FakeError


class _Fixer(NeedleSolution):
    PRIORITY = 10

    def can_fix(self):
        return True

    def fix(self):
        self.context["fixed_element"] = "ok"
        return True


def test_handle_exception_success_returns_true():
    SolutionRegistry.register(_Fixer)
    handler = ExceptionHandler(context_builder=DefaultContextBuilder())
    assert handler.handle_exception(ValueError("x")) is True


def test_handle_exception_failure_raises():
    handler = ExceptionHandler(context_builder=DefaultContextBuilder())
    with pytest.raises(RepairFailedException):
        handler.handle_exception(ValueError("x"))


def test_handle_exception_failure_no_reraise():
    handler = ExceptionHandler(
        context_builder=DefaultContextBuilder(), reraise_on_failure=False
    )
    assert handler.handle_exception(ValueError("x")) is False


def test_module_level_helper():
    SolutionRegistry.register(_Fixer)
    assert handle_exception(ValueError("x"), context_builder=DefaultContextBuilder()) is True


# --- PlaywrightContextBuilder ------------------------------------------------
def test_pw_builder_parses_locator():
    err = FakeError(
        message='Locator.click: Timeout 5000ms exceeded.',
        stack='at self.page.get_by_role("button", name="X").click(timeout=5000)',
    )
    ctx = PlaywrightContextBuilder().build(err, page=None)
    assert ctx["locator"] == 'get_by_role("button", name="X")'
    assert ctx["locator_issue"] is True


def test_pw_builder_degrades_on_plain_exception():
    # 普通异常没有 .message/.stack，不应抛错，应安全返回兜底上下文。
    ctx = PlaywrightContextBuilder().build(RuntimeError("boom"), page=None)
    assert ctx["exception"].args[0] == "boom"
    assert "locator" not in ctx


def test_find_failed_execution_no_infinite_recursion():
    # 历史 bug：_find_failed_execution 自我递归。这里确保能正常返回。
    err = FakeError(
        message="Locator.fill: Timeout exceeded.",
        stack='self.page.get_by_label("Name").fill("abc")',
    )
    builder = PlaywrightContextBuilder()
    exec_frag = builder._find_failed_execution(err)
    assert exec_frag == '"abc"'


def test_pw_builder_parses_operation_and_args():
    err = FakeError(
        message='Locator.fill: Timeout 5000ms exceeded.',
        stack='self.page.get_by_label("Name").fill("context")',
    )
    builder = PlaywrightContextBuilder()
    locator, operation, args_str = builder._find_failed_locator(err, with_operation=True)
    assert locator == 'get_by_label("Name")'
    assert operation == "fill"
    assert args_str == '"context"'


def test_pw_builder_includes_execution_args_in_context():
    err = FakeError(
        message='Locator.fill: Timeout 5000ms exceeded.',
        stack='self.page.get_by_label("Name").fill("context", timeout=3000)',
    )
    ctx = PlaywrightContextBuilder().build(err, page=None)
    assert ctx["locator_issue"] is True
    assert ctx["operation"] == "fill"
    assert ctx["execution_args"] == '"context", timeout=3000'


def test_parse_execution_args_handles_positional_and_kwargs():
    builder = PlaywrightContextBuilder()
    args, kwargs = builder._parse_execution_args('"context", timeout=3000, force=True')
    assert args == ["context"]
    assert kwargs == {"timeout": 3000, "force": True}


def test_parse_execution_args_empty():
    assert PlaywrightContextBuilder._parse_execution_args("") == ([], {})
    assert PlaywrightContextBuilder._parse_execution_args(None) == ([], {})


def test_extract_call_args_handles_parens_in_strings():
    builder = PlaywrightContextBuilder()
    stack = 'self.page.get_by_label("Name").fill("Submit (primary)")'
    locator, operation, args_str = builder._find_failed_locator(
        FakeError(message="Locator.fill: Timeout exceeded.", stack=stack),
        with_operation=True,
    )
    assert args_str == '"Submit (primary)"'
    args, kwargs = builder._parse_execution_args(args_str)
    assert args == ["Submit (primary)"]


class _FakeLocator:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def fill(self, value, *args, **kwargs):
        self.calls.append(("fill", value, args, kwargs))
        return f"filled-{value}"

    def click(self, *args, **kwargs):
        self.calls.append(("click", args, kwargs))
        return "clicked"


class _FakePage:
    def __init__(self):
        self._locators = {}

    def get_by_role(self, role, **kwargs):
        name = f"{role}-{kwargs.get('name', '')}"
        return self._locators.setdefault(name, _FakeLocator(name))

    def get_by_label(self, label):
        return self._locators.setdefault(label, _FakeLocator(label))


def test_execute_with_locator_keeps_operation_arguments():
    page = _FakePage()
    result = PlaywrightContextBuilder.execute_with_locator(
        page, 'get_by_label("Name")', "fill", '"context"'
    )
    assert result == "filled-context"
    assert page._locators["Name"].calls == [("fill", "context", (), {})]


def test_retry_with_fixed_locator_uses_new_locator():
    page = _FakePage()
    err = FakeError(
        message='Locator.fill: Timeout 5000ms exceeded.',
        stack='self.page.get_by_label("Name").fill("context")',
    )
    result = PlaywrightContextBuilder().retry_with_fixed_locator(
        page, 'get_by_role("textbox", name="Context")', err
    )
    assert result == "filled-context"
    assert "Name" not in page._locators
    assert page._locators["textbox-Context"].calls == [("fill", "context", (), {})]


def test_parse_execution_args_evaluates_variables():
    """参数是变量名时，使用传入的局部变量求值。"""
    builder = PlaywrightContextBuilder()
    args, kwargs = builder._parse_execution_args("search_text", {"search_text": "actual value"})
    assert args == ["actual value"]
    assert kwargs == {}


def test_execute_with_locator_evaluates_variables():
    page = _FakePage()
    result = PlaywrightContextBuilder.execute_with_locator(
        page,
        'get_by_label("Name")',
        "fill",
        "search_text",
        local_vars={"search_text": "actual value"},
    )
    assert result == "filled-actual value"
    assert page._locators["Name"].calls == [("fill", "actual value", (), {})]


def test_capture_stack_locals_from_real_traceback():
    """自动从真实异常的堆栈帧中捕获局部变量。"""
    search_text = "captured from stack"

    def _inner():
        raise FakeError(
            message="Locator.fill: Timeout exceeded.",
            stack='self.page.get_by_label("Name").fill(search_text)',
        )

    try:
        _inner()
    except FakeError as e:
        locals_dict = PlaywrightContextBuilder._capture_stack_locals(e)
        assert locals_dict["search_text"] == "captured from stack"
