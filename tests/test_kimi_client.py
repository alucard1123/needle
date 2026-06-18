"""KimiClient 的单元测试（mock httpx，不发起真实请求）。"""

from unittest.mock import MagicMock, patch

import pytest

from failback.builtin import KimiClient
from failback.builtin.kimi_client import KimiClient as KimiClientDirect


def _make_mock_httpx_client(response_content: str):
    """构造一个模拟的 httpx.Client，返回指定 content。"""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": response_content}}]
    }
    mock_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response
    return mock_client


def test_kimi_client_extracts_locator_from_json_response():
    """模型返回 JSON 时，应解析并转换为 Python Playwright locator 表达式。"""
    client = KimiClient(api_key="test-key")
    mock_client = _make_mock_httpx_client(
        '{"locatorType": "getByRole", "value": "button", "options": {"name": "SEARCH"}}'
    )

    with patch("httpx.Client", return_value=mock_client) as mock_client_cls:
        result = client.analyze("<html></html>", "搜索按钮")

    assert result == "get_by_role(\"button\", name=\"SEARCH\")"
    mock_client_cls.assert_called_once_with(timeout=30.0)
    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["json"]["model"] == "moonshot-v1-8k"


def test_kimi_client_strips_markdown_code_block_around_json():
    """JSON 被 markdown 代码块包裹时仍能正确解析。"""
    client = KimiClient(api_key="test-key")
    mock_client = _make_mock_httpx_client(
        '```json\n{"locatorType": "getByLabel", "value": "Name"}\n```'
    )

    with patch("httpx.Client", return_value=mock_client):
        result = client.analyze("<html></html>", "Name 输入框")

    assert result == "get_by_label(\"Name\")"


def test_kimi_client_returns_none_for_empty_content():
    client = KimiClient(api_key="test-key")
    mock_client = _make_mock_httpx_client("   ")

    with patch("httpx.Client", return_value=mock_client):
        result = client.analyze("<html></html>", "某个元素")

    assert result is None


def test_kimi_client_returns_none_for_invalid_json():
    client = KimiClient(api_key="test-key")
    mock_client = _make_mock_httpx_client("not valid json")

    with patch("httpx.Client", return_value=mock_client):
        result = client.analyze("<html></html>", "某个元素")

    assert result is None


def test_kimi_client_missing_httpx_raises_clear_error():
    client = KimiClient(api_key="test-key")

    def _fake_import(name, *args, **kwargs):
        if name == "httpx":
            raise ModuleNotFoundError("No module named 'httpx'")
        return __builtins__.__import__(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_fake_import):
        with pytest.raises(RuntimeError, match="KimiClient 需要 httpx"):
            client.analyze("<html></html>", "某个元素")


def test_extract_locator_parses_various_locator_types():
    cases = [
        (
            '{"locatorType": "getByRole", "value": "button", "options": {"name": "Submit"}}',
            'get_by_role("button", name="Submit")',
        ),
        (
            '{"locatorType": "getByLabel", "value": "Username"}',
            'get_by_label("Username")',
        ),
        (
            '{"locatorType": "getByPlaceholder", "value": "Search..."}',
            'get_by_placeholder("Search...")',
        ),
        (
            '{"locatorType": "getByText", "value": "OK"}',
            'get_by_text("OK")',
        ),
        (
            '{"locatorType": "getByTestId", "value": "submit-btn"}',
            'get_by_test_id("submit-btn")',
        ),
        (
            '{"locatorType": "css", "value": "#secondSubmit"}',
            'locator("#secondSubmit")',
        ),
        (
            '{"locatorType": "get_by_role", "value": "link", "options": {"name": "Next"}}',
            'get_by_role("link", name="Next")',
        ),
    ]
    for raw, expected in cases:
        assert KimiClientDirect._extract_locator(raw) == expected


def test_build_locator_expression_escapes_quotes():
    result = KimiClientDirect._build_locator_expression(
        "getByText", 'Say "Hello"', {}
    )
    assert result == 'get_by_text("Say \\"Hello\\"")'


def _make_raising_then_success_client(fail_count: int, status_code: int = 429):
    """构造一个前 fail_count 次抛出指定 status_code 的 httpx.Client 模拟。"""
    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {
        "choices": [{"message": {"content": '{"locatorType": "getByRole", "value": "button"}'}}]
    }

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.headers = {}
            self.text = "too many requests"

        def raise_for_status(self):
            import httpx
            raise httpx.HTTPStatusError(
                "429",
                request=MagicMock(),
                response=self,
            )

    call_count = 0

    def _post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= fail_count:
            fake = FakeResponse(status_code)
            # 让 _request_with_retry 内部的 raise_for_status 抛出异常
            fake.raise_for_status()
        return ok_response

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = _post
    return mock_client


def test_kimi_client_retries_on_429_and_succeeds():
    """遇到 429 时应指数退避重试，成功后返回解析结果。"""
    client = KimiClient(api_key="test-key", max_retries=2, backoff_factor=0.0)
    mock_client = _make_raising_then_success_client(fail_count=2)

    with patch("httpx.Client", return_value=mock_client):
        result = client.analyze("<html></html>", "某个按钮")

    assert result == 'get_by_role("button")'
    assert mock_client.post.call_count == 3


def test_kimi_client_raises_after_max_retries():
    """429 持续超过最大重试次数后应抛出异常。"""
    client = KimiClient(api_key="test-key", max_retries=2, backoff_factor=0.0)
    mock_client = _make_raising_then_success_client(fail_count=10)

    with patch("httpx.Client", return_value=mock_client):
        with pytest.raises(Exception):
            client.analyze("<html></html>", "某个按钮")

    assert mock_client.post.call_count == 3


def test_kimi_client_does_not_retry_400():
    """非限流/非瞬时错误（如 400）不应重试。"""
    client = KimiClient(api_key="test-key", max_retries=2, backoff_factor=0.0)
    mock_client = _make_raising_then_success_client(fail_count=10, status_code=400)

    with patch("httpx.Client", return_value=mock_client):
        with pytest.raises(Exception):
            client.analyze("<html></html>", "某个按钮")

    assert mock_client.post.call_count == 1
