"""内置 locator 修复策略 —— 3 种，均为 ``FailBackSolution`` 子类。

由原本写死在单个 ``LocatorSolution`` 内部的 cache→image→prompt 串行逻辑拆分而来，
现在各自独立、按 ``PRIORITY`` 自动串成责任链：

* :class:`ByCacheSolution`  (PRIORITY=10) —— 从缓存读取备选 locator 逐个尝试。
* :class:`ByImageSolution`  (PRIORITY=20) —— 用图像模板匹配按坐标定位。
* :class:`ByPromptSolution` (PRIORITY=30) —— 调用 AI 分析 DOM 给出定位建议。

每种策略的重依赖后端可注入：通过类方法 ``configure(backend=...)`` 设全局默认，
或在上下文里以 ``cache_backend`` / ``image_matcher`` / ``ai_client`` 临时覆盖。
"""

from typing import Optional
import logging
import re

from failback.builtin.backends import (
    AIClient,
    CacheBackend,
    ImageMatcher,
    OpenCVImageMatcher,
    PickleDBCacheBackend,
)
from failback.core.context import PlaywrightContextBuilder
from failback.core.solution import FailBackSolution

logger = logging.getLogger(__name__)


class _LocatorSolutionBase(FailBackSolution):
    """locator 类策略公共逻辑：要求上下文里带 ``locator`` 与 ``page``。"""

    def can_fix(self) -> bool:
        return bool(self.context.get("locator")) and self.context.get("page") is not None


class ByCacheSolution(_LocatorSolutionBase):
    """从缓存中读取备选 locator 表达式并逐个执行。"""

    PRIORITY = 10
    _backend: Optional[CacheBackend] = None

    @classmethod
    def configure(cls, backend: CacheBackend) -> None:
        cls._backend = backend

    def _get_backend(self) -> CacheBackend:
        backend = self.context.get("cache_backend") or self._backend
        if backend is None:
            backend = ByCacheSolution._backend = PickleDBCacheBackend()
        return backend

    def fix(self) -> bool:
        page = self.context.get("page")
        locator = self.context.get("locator")
        operation = self.context.get("operation")
        args_str = self.context.get("execution_args")
        local_vars = self.context.get("execution_locals")
        fallback_locators = self._get_backend().query(locator)
        if not fallback_locators:
            return False
        for action in fallback_locators:
            try:
                if operation and args_str is not None and not self._is_legacy_lambda(action):
                    # 新格式：缓存中存的是 locator 表达式，使用原始 operation + 参数重试。
                    # 例如原调用 get_by_label("Name").fill("abc")，
                    # 缓存给出 get_by_role("textbox") 时，会执行
                    # page.get_by_role("textbox").fill("abc")。
                    result = PlaywrightContextBuilder.execute_with_locator(
                        page, action, operation, args_str, local_vars
                    )
                else:
                    # 兼容旧格式：可执行 lambda 表达式
                    result = eval(action)(page)  # noqa: S307 - 备选 locator 设计为可执行表达式
                self.context["fixed_element"] = result
                return True
            except Exception:  # noqa: BLE001 - 尝试下一个备选 locator
                continue
        return False

    @staticmethod
    def _is_legacy_lambda(action: str) -> bool:
        """判断缓存条目是否为旧的 lambda 表达式格式。"""
        return action.strip().startswith("lambda")


class ByImageSolution(_LocatorSolutionBase):
    """用图像模板匹配在页面截图中定位元素，并按坐标取回 DOM 句柄。

    截图是设备物理像素，而 ``document.elementFromPoint`` 需要 CSS 逻辑像素，
    因此内部会根据 ``window.devicePixelRatio`` 自动换算坐标。
    """

    PRIORITY = 20
    _matcher: Optional[ImageMatcher] = None

    @classmethod
    def configure(cls, matcher: ImageMatcher) -> None:
        cls._matcher = matcher

    def _get_matcher(self) -> ImageMatcher:
        matcher = self.context.get("image_matcher") or self._matcher
        if matcher is None:
            matcher = ByImageSolution._matcher = OpenCVImageMatcher()
        return matcher

    def fix(self) -> bool:
        page = self.context.get("page")
        locator = self.context.get("locator")
        # locator 是类似 "get_by_role('button', name='SEARCH')" 的表达式，
        # 直接作为模板名会包含引号、括号等非法/不便文件名字符，
        # 需要先清洗为只含字母、数字、下划线的安全模板 key。
        template_key = self._sanitize_locator_for_image(locator)
        screenshot = page.screenshot()
        xy = self._get_matcher().match(screenshot, template_key)
        if not xy:
            return False
        x, y = xy

        # 截图是设备物理像素，而 document.elementFromPoint 需要 CSS 逻辑像素。
        # 用 window.devicePixelRatio 把匹配结果换算回页面坐标系。
        dpr = self._get_device_pixel_ratio(page)
        x = int(x / dpr)
        y = int(y / dpr)

        handle = page.evaluate_handle(
            "(c) => document.elementFromPoint(c.x, c.y)", {"x": x, "y": y}
        )
        element = handle.as_element()
        if element is None:
            return False

        # 识别到元素后，从上下文中获取失败的操作及参数，并在新定位到的元素上重试。
        operation = self.context.get("operation")
        args_str = self.context.get("execution_args")
        local_vars = self.context.get("execution_locals")
        if operation:
            args, kwargs = PlaywrightContextBuilder._parse_execution_args(
                args_str, local_vars
            )
            method = getattr(element, operation)
            result = method(*args, **kwargs)
            self.context["fixed_element"] = result
        else:
            self.context["fixed_element"] = element
        return True

    @staticmethod
    def _get_device_pixel_ratio(page) -> float:
        """安全读取页面 devicePixelRatio；失败时返回 1.0。"""
        try:
            dpr = page.evaluate("window.devicePixelRatio")
            if isinstance(dpr, (int, float)) and dpr > 0:
                return float(dpr)
        except Exception:
            pass
        return 1.0

    @staticmethod
    def _sanitize_locator_for_image(locator: str) -> str:
        """把 locator 表达式清洗为安全的图像模板文件名。

        只保留字母、数字和下划线，其余字符替换为下划线并合并连续下划线。
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(locator))
        sanitized = re.sub(r"_+", "_", sanitized)
        return sanitized.strip("_")


class ByPromptSolution(_LocatorSolutionBase):
    """调用 AI 客户端分析当前 DOM，给出可用的定位/操作建议。"""

    PRIORITY = 30
    _client: Optional[AIClient] = None

    @classmethod
    def configure(cls, client: AIClient) -> None:
        cls._client = client

    def _get_client(self) -> Optional[AIClient]:
        return self.context.get("ai_client") or self._client

    def fix(self) -> bool:
        client = self._get_client()
        if client is None:
            logger.warning("ByPromptSolution 未配置 AIClient，跳过。")
            return False
        page = self.context.get("page")
        description = self.context.get("description") or str(self.context.get("locator"))
        locator_str = client.analyze(page.content(), description)
        if not locator_str:
            return False

        # AI 返回新 locator 后，从上下文中获取失败的操作及参数，并用新 locator 重试。
        operation = self.context.get("operation")
        args_str = self.context.get("execution_args")
        local_vars = self.context.get("execution_locals")
        if operation:
            result = PlaywrightContextBuilder.execute_with_locator(
                page, locator_str, operation, args_str, local_vars
            )
            self.context["fixed_element"] = result
        else:
            self.context["fixed_element"] = locator_str
        return True
