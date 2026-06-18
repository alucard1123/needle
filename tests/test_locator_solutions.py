"""内置 locator 修复策略的行为。"""

from failback.builtin.locator_solutions import (
    ByCacheSolution,
    ByImageSolution,
    ByPromptSolution,
)
from failback.core.exceptions import RepairFailedException
from failback.core.registry import SolutionRegistry


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

    def content(self):
        return "fake-html"

    def get_by_role(self, role, **kwargs):
        name = f"{role}-{kwargs.get('name', '')}"
        return self._locators.setdefault(name, _FakeLocator(name))

    def get_by_label(self, label):
        return self._locators.setdefault(label, _FakeLocator(label))


class _FakeCacheBackend:
    def __init__(self, entries):
        self.entries = entries

    def query(self, key):
        return self.entries.get(key)


def test_by_cache_solution_retries_with_same_operation_and_args():
    """缓存中存的是 locator 表达式时，应使用原始 operation + 参数重试。"""
    page = _FakePage()
    backend = _FakeCacheBackend(
        {'get_by_label("Name")': ['get_by_role("textbox", name="Context")']}
    )
    ByCacheSolution.configure(backend)
    SolutionRegistry.register(ByCacheSolution)

    ctx = {
        "page": page,
        "locator": 'get_by_label("Name")',
        "operation": "fill",
        "execution_args": '"context"',
    }
    repair = RepairFailedException(context=ctx)

    assert repair.attempt_recovery() is True
    assert repair.recovered_result == "filled-context"
    assert page._locators["textbox-Context"].calls == [("fill", "context", (), {})]


def test_by_cache_solution_keeps_legacy_lambda_behavior():
    """旧的 lambda 表达式缓存格式仍应兼容。"""
    page = _FakePage()
    backend = _FakeCacheBackend(
        {'get_by_label("Name")': ['lambda p: p.get_by_role("textbox", name="Context").click()']}
    )
    ByCacheSolution.configure(backend)
    SolutionRegistry.register(ByCacheSolution)

    ctx = {
        "page": page,
        "locator": 'get_by_label("Name")',
        "operation": "fill",
        "execution_args": '"context"',
    }
    repair = RepairFailedException(context=ctx)

    assert repair.attempt_recovery() is True
    assert repair.recovered_result == "clicked"
    assert page._locators["textbox-Context"].calls == [("click", (), {})]


def test_by_cache_solution_evaluates_variable_args():
    """参数是变量名时，使用上下文中的 execution_locals 求值后再重试。"""
    page = _FakePage()
    backend = _FakeCacheBackend(
        {'get_by_label("Name")': ['get_by_role("textbox", name="Context")']}
    )
    ByCacheSolution.configure(backend)
    SolutionRegistry.register(ByCacheSolution)

    ctx = {
        "page": page,
        "locator": 'get_by_label("Name")',
        "operation": "fill",
        "execution_args": "search_text",
        "execution_locals": {"search_text": "actual value"},
    }
    repair = RepairFailedException(context=ctx)

    assert repair.attempt_recovery() is True
    assert repair.recovered_result == "filled-actual value"
    assert page._locators["textbox-Context"].calls == [("fill", "actual value", (), {})]


class _FakeImageMatcher:
    def __init__(self):
        self.calls = []

    def match(self, screenshot, template_name):
        self.calls.append((screenshot, template_name))
        return (100, 200)


class _FakeImageElement:
    def __init__(self):
        self.calls = []

    def fill(self, value, *args, **kwargs):
        self.calls.append(("fill", value, args, kwargs))
        return f"filled-{value}"

    def click(self, *args, **kwargs):
        self.calls.append(("click", args, kwargs))
        return "clicked"


class _FakeImagePage:
    def __init__(self, dpr=1.0):
        self.dpr = dpr
        self._evaluated = []
        self._element = _FakeImageElement()

    def screenshot(self):
        return b"fake-screenshot"

    def evaluate(self, script):
        self._evaluated.append(script)
        return self.dpr

    def evaluate_handle(self, script, arg):
        self._evaluated.append((script, arg))

        class Handle:
            def __init__(self, element):
                self._element = element

            def as_element(self):
                return self._element
        return Handle(self._element)


def test_by_image_solution_sanitizes_locator_for_template_name():
    """locator 表达式应先清洗为安全模板名再传给 ImageMatcher。"""
    matcher = _FakeImageMatcher()
    ByImageSolution.configure(matcher)
    SolutionRegistry.register(ByImageSolution)

    ctx = {
        "page": _FakeImagePage(),
        "locator": "get_by_role('button', name='SEARCH')",
    }
    repair = RepairFailedException(context=ctx)

    assert repair.attempt_recovery() is True
    assert repair.recovered_result is ctx["page"]._element
    assert len(matcher.calls) == 1
    _screenshot, template_name = matcher.calls[0]
    assert template_name == "get_by_role_button_name_SEARCH"


def test_by_image_solution_scales_coordinates_by_dpr():
    """匹配结果应按 devicePixelRatio 换算为 CSS 逻辑坐标。"""
    matcher = _FakeImageMatcher()
    matcher.match = lambda screenshot, template_name: (200, 400)
    ByImageSolution.configure(matcher)
    SolutionRegistry.register(ByImageSolution)

    page = _FakeImagePage(dpr=2.0)
    ctx = {
        "page": page,
        "locator": "get_by_role('button', name='SEARCH')",
    }
    repair = RepairFailedException(context=ctx)

    assert repair.attempt_recovery() is True
    assert repair.recovered_result is page._element

    # matcher 返回的是物理像素 (200, 400)，DPR=2.0
    # 传给 elementFromPoint 的应该是 CSS 逻辑像素 (100, 200)
    assert ("(c) => document.elementFromPoint(c.x, c.y)", {"x": 100, "y": 200}) in page._evaluated


def test_by_image_solution_retries_with_same_operation_and_args():
    """图像匹配定位到元素后，应使用原始 operation + 参数在新元素上重试。"""
    matcher = _FakeImageMatcher()
    ByImageSolution.configure(matcher)
    SolutionRegistry.register(ByImageSolution)

    page = _FakeImagePage()
    ctx = {
        "page": page,
        "locator": "get_by_role('button', name='SEARCH')",
        "operation": "fill",
        "execution_args": '"search term"',
    }
    repair = RepairFailedException(context=ctx)

    assert repair.attempt_recovery() is True
    assert repair.recovered_result == "filled-search term"
    assert page._element.calls == [("fill", "search term", (), {})]


class _FakeAIClient:
    def __init__(self, locator_str):
        self.locator_str = locator_str
        self.calls = []

    def analyze(self, html: str, description: str):
        self.calls.append((html, description))
        return self.locator_str


def test_by_prompt_solution_returns_locator_without_operation():
    """未提供 operation 时，ByPromptSolution 直接返回 AI 建议的 locator 字符串。"""
    ai_client = _FakeAIClient('get_by_role("button", name="AI")')
    ByPromptSolution.configure(ai_client)
    SolutionRegistry.register(ByPromptSolution)

    page = _FakePage()
    ctx = {
        "page": page,
        "locator": 'get_by_label("Name")',
    }
    repair = RepairFailedException(context=ctx)

    assert repair.attempt_recovery() is True
    assert repair.recovered_result == 'get_by_role("button", name="AI")'
    assert ai_client.calls[0][0] == "fake-html"
    assert ai_client.calls[0][1] == 'get_by_label("Name")'


def test_by_prompt_solution_retries_with_same_operation_and_args():
    """AI 返回新 locator 后，应使用原始 operation + 参数在新 locator 上重试。"""
    ai_client = _FakeAIClient('get_by_role("textbox", name="Context")')
    ByPromptSolution.configure(ai_client)
    SolutionRegistry.register(ByPromptSolution)

    page = _FakePage()
    ctx = {
        "page": page,
        "locator": 'get_by_label("Name")',
        "operation": "fill",
        "execution_args": '"context"',
    }
    repair = RepairFailedException(context=ctx)

    assert repair.attempt_recovery() is True
    assert repair.recovered_result == "filled-context"
    assert page._locators["textbox-Context"].calls == [("fill", "context", (), {})]
