# failback

自动化测试**异常自愈**库。捕获到异常时交给 `handle_exception`，由责任链
（chain of responsibility）查找一个能处理它的 `FailBackSolution` 并尝试修复。

- **核心零依赖**：`handler` / `registry` / 基类 / 异常 / 装饰器 不引入任何第三方库。
- **内置 3 种 locator 修复策略**：缓存（cache）、图像（image）、提示词（prompt）。
- **可扩展**：继承 `FailBackSolution` 实现 `can_fix` / `fix`，注册即用。

## 安装

```bash
pip install failback                 # 仅核心
pip install "failback[cache]"        # 缓存策略（零依赖，JSON 文件）
pip install "failback[image]"        # + opencv 图像策略
pip install "failback[ai]"           # + AI 策略依赖
pip install "failback[all]"          # 全部内置策略
```

## 快速开始

```python
from failback import ExceptionHandler
from failback.builtin import register_builtins

register_builtins()  # 注册内置策略（可选）

try:
    page.get_by_role("button", name="SEARCH").click(timeout=5000)
except Exception as e:
    ExceptionHandler(page=page).handle_exception(e)
    # 修复成功：正常返回；全部策略失败：抛出 RepairFailedException
```

也可用模块级便捷函数：

```python
from failback import handle_exception
handle_exception(e, page=page)
```

## 扩展：自定义修复策略

只需继承 `FailBackSolution` 并实现 `can_fix` / `fix`，然后注册：

```python
from failback import FailBackSolution, register_solution

@register_solution
class MyRetrySolution(FailBackSolution):
    PRIORITY = 5  # 数字越小越先尝试

    def can_fix(self) -> bool:
        return "locator" in self.context

    def fix(self) -> bool:
        page, locator = self.context["page"], self.context["locator"]
        page.locator(locator).click()
        self.context["fixed_element"] = locator  # 可选：记录修复结果
        return True
```

## 调用链

```
ExceptionHandler.handle_exception(e)
  └─ ContextBuilder.build(e)            # 异常 → 修复上下文 dict（可替换）
  └─ RepairFailedException.attempt_recovery()
       └─ SolutionRegistry.create_chain(ctx)   # 按 PRIORITY 组装责任链
            └─ FailBackSolution.handle(ctx)     # 逐个 can_fix → fix
```

## 注入重依赖后端

内置策略的重依赖通过协议注入，可用宿主项目自己的实现替换默认实现：

```python
from failback.builtin import ByCacheSolution, ByImageSolution, ByPromptSolution

ByCacheSolution.configure(my_cache_backend)     # CacheBackend
ByImageSolution.configure(my_image_matcher)     # ImageMatcher
ByPromptSolution.configure(my_ai_client)        # AIClient
```

### 默认后端的实例化

```python
from failback.builtin import (
    ByCacheSolution,
    ByImageSolution,
    ByPromptSolution,
    PickleDBCacheBackend,
    OpenCVImageMatcher,
    AIClient,
)

# 1. 缓存后端：JSON 文件，key 为原 locator，value 为备选 locator 列表
my_cache_backend = PickleDBCacheBackend(db_path="failback_locator_cache.db")
ByCacheSolution.configure(my_cache_backend)

# 2. 图像匹配后端：OpenCV 模板匹配
my_image_matcher = OpenCVImageMatcher(
    image_dir="image_locator",  # 模板图片目录
    threshold=0.8,              # 匹配阈值，范围 0~1
)
ByImageSolution.configure(my_image_matcher)
```

### 自定义 AI 客户端（ByPromptSolution 必须）

``failback`` 没有内置通用 LLM 客户端，需要你自己实现 ``AIClient`` 协议：

```python
from typing import Optional

class MyAIClient(AIClient):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model = model

    def analyze(self, html: str, description: str) -> Optional[str]:
        """根据页面 HTML 和描述返回一个可用的 Playwright locator 表达式。

        返回 None 表示无法给出建议；返回的字符串会被写入 ``context["fixed_element"]``。
        """
        prompt = (
            f"根据以下页面 HTML，给出一个能定位到「{description}」的 "
            f"Playwright locator 表达式。只返回表达式本身，不要任何解释。\n\n"
            f"{html[:8000]}"
        )
        # 这里接入你实际使用的 LLM（OpenAI / Kimi / Claude / 自部署模型等）
        # response = call_your_llm(prompt)
        # return response.strip()
        raise NotImplementedError("请接入实际的 LLM API")


my_ai_client = MyAIClient(api_key="sk-xxx")
ByPromptSolution.configure(my_ai_client)
```

### 内置 Kimi / Moonshot 客户端

``failback`` 内置了一个基于 Moonshot AI（Kimi）的 ``AIClient`` 实现，
安装 ``ai`` 依赖后即可使用：

```bash
pip install "failback[ai]"   # 包含 aiohttp + httpx
```

```python
from failback.builtin import ByPromptSolution, KimiClient

my_ai_client = KimiClient(
    api_key="sk-xxxxxxxxxxxxxxxx",  # Moonshot API Key
    model="moonshot-v1-8k",         # 可选：moonshot-v1-32k / moonshot-v1-128k
    base_url="https://api.moonshot.cn/v1",
    temperature=0.1,
    max_tokens=512,
)
ByPromptSolution.configure(my_ai_client)
```

> **注意**：`ByPromptSolution` 在未配置 `AIClient` 时会直接跳过，因此如果只使用缓存/图像策略，可以不实现 AI 客户端。
