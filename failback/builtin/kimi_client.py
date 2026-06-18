"""基于 Moonshot AI (Kimi) 的 ``AIClient`` 实现。

重依赖 ``httpx`` 采用懒加载；缺失时给出清晰的安装提示。
"""

import json
import logging
import random
import time
from typing import Any, Dict, Optional, Tuple

from failback.builtin.backends import AIClient

logger = logging.getLogger(__name__)


class KimiClient(AIClient):
    """调用 Kimi / Moonshot API 分析页面 DOM，给出 Playwright 定位建议。"""

    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
    DEFAULT_MODEL = "moonshot-v1-8k"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        max_backoff: float = 60.0,
        retry_status_codes: Optional[Tuple[int, ...]] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        self.retry_status_codes = retry_status_codes or (429, 502, 503, 504)

    def analyze(self, html: str, description: str) -> Optional[str]:
        """根据 HTML 与描述返回一个 Playwright locator 表达式；失败返回 None。"""
        try:
            import httpx  # noqa: PLC0415 - 懒加载重依赖
        except ImportError as e:
            raise RuntimeError(
                "KimiClient 需要 httpx，请安装：pip install httpx"
            ) from e

        prompt = self._build_prompt(html, description)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Playwright automation expert. "
                        "Return only valid JSON as requested, with no extra explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = self._request_with_retry(
                client,
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            data = response.json()

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content:
            return None
        return self._extract_locator(content)

    def _request_with_retry(
        self,
        client,
        url: str,
        headers: Dict[str, str],
        json: Dict[str, Any],
    ):
        """发送请求并在遇到限流或瞬时错误时按指数退避重试。"""
        import httpx  # noqa: PLC0415 - 与 analyze 保持一致，懒加载

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.post(url, headers=headers, json=json)
                if response.status_code not in self.retry_status_codes:
                    response.raise_for_status()
                    return response
            except Exception as e:  # noqa: BLE001 - 网络/超时异常需要重试
                last_error = e
                # 非限流类 HTTPStatusError 不重试（如 401/403/400）
                if isinstance(e, httpx.HTTPStatusError):
                    if e.response.status_code not in self.retry_status_codes:
                        raise

            if attempt >= self.max_retries:
                break

            wait = self._compute_wait(attempt, last_error)
            logger.warning(
                "KimiClient 请求失败（%d/%d），%.1f 秒后重试：%s",
                attempt + 1,
                self.max_retries + 1,
                wait,
                last_error,
            )
            time.sleep(wait)

        if last_error is not None:
            raise last_error
        raise httpx.HTTPError("KimiClient 请求在重试后仍然失败")

    def _compute_wait(
        self, attempt: int, last_error: Optional[Exception]
    ) -> float:
        """计算下一次重试前的等待秒数。

        优先尊重服务端返回的 ``Retry-After`` 头；否则使用指数退避 + 抖动。
        """
        import httpx  # noqa: PLC0415 - 与 analyze 保持一致，懒加载

        retry_after = None
        if isinstance(last_error, httpx.HTTPStatusError):
            retry_after_header = last_error.response.headers.get("Retry-After")
            if retry_after_header:
                try:
                    retry_after = float(retry_after_header)
                except ValueError:
                    pass

        if retry_after is not None and retry_after > 0:
            base_wait = retry_after
        else:
            base_wait = self.backoff_factor * (2 ** attempt)

        # 加入少量抖动，避免并发请求在同一时刻重试
        jitter = random.uniform(0, 1)
        return min(base_wait + jitter, self.max_backoff)

    @staticmethod
    def _build_prompt(html: str, description: str) -> str:
        """构造给 Kimi 的提示词，要求模型返回结构化 JSON。"""
        return (
            f'You are a Playwright automation expert. Find the best UNIQUE locator for: "{description}"\n'
            "\n"
            "Analyze the HTML and find the correct element.\n"
            "\n"
            f"HTML:\n{html[:8000]}\n"
            "\n"
            "CRITICAL REQUIREMENT:\n"
            "The locator MUST match EXACTLY ONE element. If multiple elements have the same text/role, "
            "you MUST use a unique identifier like ID, data-testid, or a more specific CSS selector.\n"
            "\n"
            "PRIORITY ORDER (try in this sequence, but ONLY if it matches exactly one element):\n"
            '1. getByTestId() - Use the VALUE of the data-test or data-testid attribute (NOT the id attribute) - PREFERRED\n'
            '2. css with ID - CSS selector with #id (e.g., "#secondSubmit") - VERY RELIABLE\n'
            '3. getByRole() - ARIA role with accessible name - ONLY if unique\n'
            '4. getByLabel() - Form label text associated with input\n'
            '5. getByPlaceholder() - Input placeholder text\n'
            '6. getByText() - Visible text content - ONLY if unique\n'
            '7. CSS Selector - Fallback with class or attribute selectors\n'
            "\n"
            "RULES:\n"
            "- MOST IMPORTANT: The locator must match exactly ONE element, not multiple\n"
            '- For getByTestId(): use the VALUE of the data-test or data-testid HTML attribute, NOT the id attribute value\n'
            '  Example: for <input id="user-name" data-test="username"> use getByTestId("username"), NOT getByTestId("user-name")\n'
            '- If description mentions "first", "second", "last" etc., find the specific element by its unique ID or data-testid\n'
            "- If multiple elements have the same text (e.g., two \"Submit\" buttons), use ID or data-testid instead of getByRole/getByText\n"
            "- Look for data-test, data-testid, and id attributes first - they are usually unique\n"
            "- Avoid locators that would match multiple elements\n"
            "\n"
            "Respond with valid JSON only:\n"
            "{\n"
            '    "locatorType": "getByRole|getByLabel|getByPlaceholder|getByText|getByTestId|css",\n'
            '    "value": "button|Username|#secondSubmit",\n'
            '    "options": {"name": "Submit"},\n'
            '    "confidence": 0.95,\n'
            '    "reasoning": "brief explanation why this locator was chosen",\n'
            '    "alternatives": [\n'
            '        {"type": "css", "value": "#username"},\n'
            '        {"type": "getByTestId", "value": "user-input"}\n'
            "    ]\n"
            "}\n"
            "\n"
            "Examples:\n"
            '- Second button with ID: {"locatorType": "css", "value": "#secondSubmit", "confidence": 0.98, "reasoning": "Using unique ID for the second Submit button"}\n'
            '- Button with test-id: {"locatorType": "getByTestId", "value": "submit-second", "confidence": 0.95}\n'
            '- Unique button: {"locatorType": "getByRole", "value": "button", "options": {"name": "Login"}}\n'
            '- Input with label: {"locatorType": "getByLabel", "value": "Username"}\n'
            "- Fallback CSS: {\"locatorType\": \"css\", \"value\": \"[data-testid='submit-second']\"}"
        )

    @staticmethod
    def _extract_locator(content: str) -> Optional[str]:
        """清理模型输出，解析 JSON 并转换为 Playwright locator 表达式字符串。"""
        cleaned = KimiClient._clean_markdown(content)
        if not cleaned:
            return None

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning("KimiClient 无法解析 JSON 响应: %s", e)
            return None

        if not isinstance(data, dict):
            logger.warning("KimiClient 响应不是 JSON 对象: %r", data)
            return None

        locator_type = data.get("locatorType") or data.get("locator_type")
        value = data.get("value")
        if not locator_type or not value:
            logger.warning("KimiClient 响应缺少 locatorType 或 value: %r", data)
            return None

        options = data.get("options") or {}
        if not isinstance(options, dict):
            options = {}
        return KimiClient._build_locator_expression(locator_type, value, options)

    @staticmethod
    def _clean_markdown(content: str) -> str:
        """去掉可能的 markdown 代码块与首尾空白。"""
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned

    @staticmethod
    def _build_locator_expression(
        locator_type: str, value: str, options: Dict[str, Any]
    ) -> str:
        """把模型返回的 locator 元信息转换为 Python Playwright 表达式字符串。"""
        normalized = KimiClient._normalize_locator_type(locator_type)

        if normalized == "get_by_role":
            name = options.get("name")
            if name is not None:
                return f'get_by_role("{KimiClient._escape(value)}", name="{KimiClient._escape(str(name))}")'
            return f'get_by_role("{KimiClient._escape(value)}")'

        if normalized == "get_by_label":
            return f'get_by_label("{KimiClient._escape(value)}")'

        if normalized == "get_by_placeholder":
            return f'get_by_placeholder("{KimiClient._escape(value)}")'

        if normalized == "get_by_text":
            return f'get_by_text("{KimiClient._escape(value)}")'

        if normalized == "get_by_alt_text":
            return f'get_by_alt_text("{KimiClient._escape(value)}")'

        if normalized == "get_by_title":
            return f'get_by_title("{KimiClient._escape(value)}")'

        if normalized == "get_by_test_id":
            return f'get_by_test_id("{KimiClient._escape(value)}")'

        if normalized in ("css_selector", "css", "xpath"):
            return f'locator("{KimiClient._escape(value)}")'

        logger.warning("未知的 locatorType: %s，回退为 css locator", locator_type)
        return f'locator("{KimiClient._escape(value)}")'

    @staticmethod
    def _normalize_locator_type(locator_type: str) -> str:
        """统一 locatorType 为 snake_case。"""
        normalized = locator_type.strip().lower()
        if normalized.startswith("getby"):
            normalized = "get_by_" + normalized[5:]
        # 处理模型返回的 camelCase 复合词，如 getByTestId / getByAltText
        camel_compounds = {
            "get_by_testid": "get_by_test_id",
            "get_by_alttext": "get_by_alt_text",
        }
        return camel_compounds.get(normalized, normalized)

    @staticmethod
    def _escape(value: str) -> str:
        """转义字符串中的反斜杠与双引号，便于嵌入 Python 字符串字面量。"""
        return value.replace("\\", "\\\\").replace('"', '\\"')
