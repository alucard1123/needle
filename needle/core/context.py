"""ContextBuilder —— 把原始异常翻译成「修复上下文」（核心零依赖）。

修复策略不直接面对千奇百怪的异常对象，而是面对一个统一的上下文字典。
``ContextBuilder`` 负责这层翻译，是可替换的：

* :class:`DefaultContextBuilder` —— 通用兜底，原样打包异常与传入的关键字。
* :class:`PlaywrightContextBuilder` —— 解析 Playwright 报错的 ``message`` / ``stack``，
  识别 timeout / locator 两类异常并填充对应字段（``timeout_status`` / ``locator`` 等）。

核心层不硬依赖 playwright；``PlaywrightContextBuilder`` 仅在 :meth:`build` 被传入
``page`` 时才会调用 page 的方法，且对非 Playwright 异常安全降级。
"""

from typing import Optional, Protocol, runtime_checkable
import ast
import re
import sys
import traceback


@runtime_checkable
class ContextBuilder(Protocol):
    """上下文构建器协议：把异常翻译为修复策略可消费的 dict（无法处理时返回 None）。"""

    def build(self, exception: Exception, *, page=None, **kwargs) -> Optional[dict]:
        ...


class DefaultContextBuilder:
    """通用兜底构建器：原样打包异常、page 及其它关键字。"""

    def build(self, exception: Exception, *, page=None, **kwargs) -> Optional[dict]:
        context = {"exception": exception, **kwargs}
        if page is not None:
            context["page"] = page
        return context


def _err_message(exception: Exception) -> str:
    """安全获取异常文本：Playwright 异常有 ``.message``，普通异常退化为 str()。"""
    return getattr(exception, "message", None) or str(exception)


def _err_stack(exception: Exception) -> str:
    """安全获取异常栈文本（普通异常通常没有 ``.stack``）。"""
    return getattr(exception, "stack", "") or ""


class PlaywrightContextBuilder:
    """解析 Playwright 报错，识别 timeout / locator 异常并构建上下文。

    ``LOCATOR_OPERATION_LIST`` 列出需要从异常栈中识别的 Locator/Page 操作。
    """

    LOCATOR_OPERATION_LIST = ["click", "count", "fill"]

    def __init__(self, locator_operations: Optional[list] = None):
        if locator_operations is not None:
            self.LOCATOR_OPERATION_LIST = locator_operations

    def build(self, exception: Exception, *, page=None, **kwargs) -> Optional[dict]:
        # 自动从异常堆栈捕获局部变量，供解析变量型参数使用；用户也可通过
        # handle_exception(..., execution_locals={...}) 显式覆盖/补充。
        execution_locals = kwargs.pop("execution_locals", None)
        if execution_locals is None:
            execution_locals = self._capture_stack_locals(exception)

        # 1. 优先判断是否是环境型 timeout（需要 page 才能探测）。
        timeout_status = self._check_timeout(page) if page is not None else 0
        if timeout_status > 0:
            return {
                "page": page,
                "timeout_status": timeout_status,
                "exception": exception,
                "execution": self._find_failed_execution(exception, execution_locals),
                "execution_locals": execution_locals,
                **kwargs,
            }

        # 2. 判断是否是定位符异常。
        if self._check_locator_fail(exception, timeout_status):
            locator, operation, args_str = self._find_failed_locator(exception, with_operation=True)
            return {
                "page": page,
                "locator_issue": True,
                "exception": exception,
                "locator": locator,
                "operation": operation,
                "execution_args": args_str,
                "execution_locals": execution_locals,
                **kwargs,
            }

        # 3. 其它类型暂不识别，交回 DefaultContextBuilder 风格的兜底。
        context = {"exception": exception, **kwargs}
        if page is not None:
            context["page"] = page
        return context

    # ------------------------------------------------------------------ #
    # 识别辅助方法
    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_locator_fail(exception: Exception, timeout_status: int = 0) -> bool:
        err_msg = _err_message(exception)
        locator_in_err = "Locator" in err_msg
        timeout_by_locator = "Timeout" in err_msg and timeout_status == 0
        confirm_tail = "exceeded" in err_msg
        return locator_in_err and timeout_by_locator and confirm_tail

    @staticmethod
    def _check_timeout(page) -> int:
        """探测环境型超时：

        1. 页面有 "Please wait..." 字样
        2. 出现 "Validation error has occurred" 页面
        3. 页面长时间无法进入 load 状态
        """
        try:
            if page.get_by_text("Please wait...", exact=True).is_visible():
                return 1
            if page.get_by_text("Validation error has occurred", exact=True).count() > 0:
                return 2
            try:
                page.wait_for_load_state(state="load", timeout=60000)
            except Exception:
                return 3
        except Exception:
            # page 不是合法的 Playwright Page，或探测过程出错 —— 视作非超时。
            return 0
        return 0

    @staticmethod
    def _capture_stack_locals(exception: Exception) -> dict:
        """从异常堆栈的各帧中收集局部变量，用于解析变量型调用参数。

        越内层的帧优先级越高，会覆盖外层同名变量。若异常对象没有 traceback
        （或已被清理），则返回空字典。
        """
        tb = getattr(exception, "__traceback__", None) or sys.exc_info()[2]
        if tb is None:
            return {}
        locals_dict: dict = {}
        for frame, _lineno in traceback.walk_tb(tb):
            locals_dict.update(frame.f_locals)
        return locals_dict

    def _find_failed_locator(self, exception: Exception, with_operation: bool = False):
        """从异常 message/stack 中解析出失败的 locator 表达式、操作名及调用参数。

        返回 ``(locator, operation, args_str)`` 或仅 ``locator``；
        解析失败时对应位置返回 ``None``。
        """
        message = _err_message(exception)
        stack = _err_stack(exception)
        if not re.search(r"Locator\.(\w+):", message):
            return (None, None, None) if with_operation else None

        for operation_mark in self.LOCATOR_OPERATION_LIST:
            match = re.search(r"self\.page\.(.*?)\." + operation_mark, stack, re.S)
            if match:
                locator = match.group(1)
                args_str = self._extract_call_args(stack[match.start():], operation_mark)
                return (locator, operation_mark, args_str) if with_operation else locator
        return (None, None, None) if with_operation else None

    @staticmethod
    def _extract_call_args(text: str, operation_mark: str) -> Optional[str]:
        """从 ``self.page.<locator>.<operation_mark>(...)`` 片段中提取括号内参数。

        支持字符串内嵌括号和简单嵌套调用，返回不含最外层括号的参数文本。
        """
        prefix = "." + operation_mark + "("
        idx = text.find(prefix)
        if idx == -1:
            return None
        start = idx + len(prefix)
        depth = 1
        i = start
        in_string = None
        while i < len(text) and depth > 0:
            ch = text[i]
            if in_string:
                if ch == "\\" and i + 1 < len(text):
                    i += 2
                    continue
                if ch == in_string:
                    in_string = None
            elif ch in ('"', "'"):
                in_string = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return text[start:i]
            i += 1
        return None

    @staticmethod
    def _parse_execution_args(args_str: Optional[str], local_vars: Optional[dict] = None):
        """把异常栈中的参数片段安全解析为 ``(args, kwargs)``。

        字面量使用 ``ast.literal_eval``；变量/表达式则使用捕获的局部变量进行求值。
        若解析失败会抛出 ``SyntaxError`` / ``ValueError``。
        """
        if not args_str or not args_str.strip():
            return [], {}
        expr = ast.parse(f"__invoke__({args_str})", mode="eval")
        call = expr.body
        local_vars = local_vars or {}

        def _eval_node(node):
            try:
                return ast.literal_eval(node)
            except ValueError:
                code = compile(ast.Expression(node), "<needle>", "eval")
                return eval(code, {}, local_vars)  # noqa: S307 - 局部变量来自用户代码堆栈

        args = [_eval_node(arg) for arg in call.args]
        kwargs = {kw.arg: _eval_node(kw.value) for kw in call.keywords}
        return args, kwargs

    @classmethod
    def execute_with_locator(
        cls,
        page,
        locator_str: str,
        operation: str,
        args_str: Optional[str],
        local_vars: Optional[dict] = None,
    ):
        """在指定 locator 上重放原 Playwright 操作，保持调用参数一致。

        ``locator_str`` 为 ``get_by_role("button", name="X")`` 形式的表达式，
        会通过 ``page.<locator_str>`` 解析为 Locator 对象后调用对应方法。
        """
        if not operation:
            raise ValueError("operation 不能为空")
        args, kwargs = cls._parse_execution_args(args_str, local_vars)
        locator_obj = eval("page." + locator_str)  # noqa: S307 - locator 来自受控解析
        method = getattr(locator_obj, operation)
        return method(*args, **kwargs)

    def retry_with_fixed_locator(
        self,
        page,
        fixed_locator_str: str,
        exception: Exception,
        local_vars: Optional[dict] = None,
    ):
        """用修复后的 locator 自动重试原始 Playwright 操作，保持调用参数一致。"""
        _locator, operation, args_str = self._find_failed_locator(exception, with_operation=True)
        if not operation:
            raise ValueError("无法从异常中解析出 Playwright 操作，无法重试")
        if local_vars is None:
            local_vars = self._capture_stack_locals(exception)
        return self.execute_with_locator(page, fixed_locator_str, operation, args_str, local_vars)

    def _find_failed_execution(self, exception: Exception, local_vars: Optional[dict] = None):
        """解析失败操作的调用参数片段（依赖能先定位到 locator + 操作名）。"""
        locator, operation_mark, args_str = self._find_failed_locator(exception, with_operation=True)
        if not locator or not operation_mark:
            return None
        return args_str
