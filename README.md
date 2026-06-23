# needle

[![PyPI](https://img.shields.io/pypi/v/needle.svg)](https://pypi.org/project/needle-fixer/)
[![Python](https://img.shields.io/pypi/pyversions/needle.svg)](https://pypi.org/project/needle-fixer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-pytest-blue.svg)](./tests)

> 自动化测试异常自愈（Self-Healing）库。
>
> 当 Playwright / Selenium / 任意自动化脚本抛出异常时，`needle` 会按「责任链」模式自动寻找并执行可用的修复策略，把原本会失败的用例救回来。

```python
from needle import ExceptionHandler
from needle.builtin import register_builtins

register_builtins()  # 注册内置修复策略（可选）

try:
    page.get_by_role("button", name="SEARCH").click(timeout=5000)
except Exception as e:
    ExceptionHandler(page=page).handle_exception(e)
    # 修复成功：正常返回；全部失败：抛出 RepairFailedException
```

---

## 目录

- [needle](#needle)
  - [目录](#目录)
  - [特性](#特性)
  - [安装](#安装)
  - [快速开始](#快速开始)
    - [1. 模块级便捷函数](#1-模块级便捷函数)
    - [2. 类级入口](#2-类级入口)
    - [3. 装饰器模式](#3-装饰器模式)
  - [核心概念](#核心概念)
  - [内置修复策略](#内置修复策略)
  - [自定义修复策略](#自定义修复策略)
  - [注入自定义后端](#注入自定义后端)
    - [默认后端的实例化](#默认后端的实例化)
    - [自定义 AI 客户端（ByPromptSolution 必须）](#自定义-ai-客户端bypromptsolution-必须)
    - [内置 Kimi / Moonshot 客户端](#内置-kimi--moonshot-客户端)
  - [装饰器模式](#装饰器模式)
  - [开发与测试](#开发与测试)
  - [许可证](#许可证)
  - [关于作者](#关于作者)

---

## 特性

- **核心零依赖**：`handler` / `registry` / 基类 / 异常 / 装饰器 仅使用 Python 标准库。
- **责任链调度**：按 `PRIORITY` 自动排序，逐个尝试 `can_fix → fix`，单个策略失败不会打断后续策略。
- **Playwright 原生友好**：自动解析 `Locator` 超时异常，提取原始 locator、操作名与调用参数，修复后可保持参数一致重试。
- **多种内置策略**：缓存、图像模板匹配、AI 提示词、环境型超时处理，按需安装依赖。
- **可插拔后端**：重依赖（OpenCV、LLM 客户端）通过协议注入，可替换为项目自有实现。
- **易于扩展**：继承 `NeedleSolution` 实现 `can_fix` / `fix`，注册即用。

---

## 安装

```bash
# 仅安装核心（零依赖）
pip install needle-fixer

# 图像策略（OpenCV 模板匹配）
pip install "needle-fixer[image]"

# AI 策略（内置 Kimi / Moonshot 客户端）
pip install "needle-fixer[ai]"

# Playwright 运行时（如项目尚未安装）
pip install "needle-fixer[playwright]"

# 全部可选依赖
pip install "needle-fixer[all]"

# 开发依赖
pip install "needle-fixer[dev]"
```

> **注意**：缓存策略基于 JSON 文件，零依赖，已包含在核心包中。

---

## 快速开始

### 1. 模块级便捷函数

```python
from needle import handle_exception
from needle.builtin import register_builtins

register_builtins()

try:
    page.get_by_role("button", name="SEARCH").click(timeout=5000)
except Exception as e:
    handle_exception(e, page=page)
```

### 2. 类级入口

```python
from needle import ExceptionHandler
from needle.builtin import register_builtins

register_builtins()

handler = ExceptionHandler(page=page)
try:
    page.get_by_label("Name").fill("needle")
except Exception as e:
    handler.handle_exception(e)
```

### 3. 装饰器模式

```python
from needle import with_recovery

@with_recovery(
    context_extractor=lambda page, locator, **kw: {
        "page": page,
        "locator": locator,
        **kw,
    }
)
def click_element(page, locator):
    page.locator(locator).click()

click_element(page, "#submit")
```

---

## 核心概念

```
ExceptionHandler.handle_exception(e)
  └─ ContextBuilder.build(e)            # 异常 → 修复上下文 dict（可替换）
  └─ RepairFailedException.attempt_recovery()
       └─ SolutionRegistry.create_chain(ctx)   # 按 PRIORITY 组装责任链
            └─ NeedleSolution.handle(ctx)     # 逐个 can_fix → fix
```

| 组件 | 职责 |
|------|------|
| `ExceptionHandler` | 统一入口，负责构建上下文并触发修复。 |
| `ContextBuilder` | 把原始异常翻译成修复策略可消费的 `dict`。内置 `PlaywrightContextBuilder` 与 `DefaultContextBuilder`。 |
| `SolutionRegistry` | 策略注册中心，维护优先级排序，负责建链。 |
| `NeedleSolution` | 修复策略基类，子类实现 `can_fix` / `fix`。 |
| `RepairFailedException` | 修复失败时抛出，通过 `__cause__` 保留原始异常。 |

---

## 内置修复策略

| 策略 | 优先级 | 说明 | 依赖 |
|------|--------|------|------|
| `ByCacheSolution` | 10 | 从 JSON 缓存读取备选 locator 逐个尝试。 | 无 |
| `ByImageSolution` | 20 | OpenCV 模板匹配，按坐标定位元素。 | `opencv-python`, `numpy`, `Pillow` |
| `ByPromptSolution` | 30 | 调用 AI 分析 DOM，给出新 locator。 | `httpx` |
| `TimeoutSolution` | 50 | 处理环境型超时（如页面出现 waiting 提示）。 | 无 |

使用全部内置策略：

```python
from needle.builtin import register_builtins

register_builtins()
```

或单独注册：

```python
from needle.core.registry import SolutionRegistry
from needle.builtin import ByCacheSolution, ByImageSolution

SolutionRegistry.register(ByCacheSolution)
SolutionRegistry.register(ByImageSolution)
```

---

## 自定义修复策略

只需继承 `NeedleSolution` 并实现 `can_fix` / `fix`，然后注册：

```python
from needle import NeedleSolution, register_solution

@register_solution
class MyRetrySolution(NeedleSolution):
    PRIORITY = 5  # 数字越小越先尝试

    def can_fix(self) -> bool:
        return "locator" in self.context

    def fix(self) -> bool:
        page, locator = self.context["page"], self.context["locator"]
        page.locator(locator).click()
        self.context["fixed_element"] = locator  # 可选：记录修复结果
        return True
```

---

## 注入自定义后端

内置策略的重依赖通过协议注入，可用宿主项目自己的实现替换默认实现：

```python
from needle.builtin import ByCacheSolution, ByImageSolution, ByPromptSolution

ByCacheSolution.configure(my_cache_backend)     # CacheBackend
ByImageSolution.configure(my_image_matcher)     # ImageMatcher
ByPromptSolution.configure(my_ai_client)        # AIClient
```

### 默认后端的实例化

```python
from needle.builtin import (
    ByCacheSolution,
    ByImageSolution,
    ByPromptSolution,
    PickleDBCacheBackend,
    OpenCVImageMatcher,
)

# 1. 缓存后端：JSON 文件，key 为原 locator，value 为备选 locator 列表
my_cache_backend = PickleDBCacheBackend(db_path="needle_locator_cache.db")
ByCacheSolution.configure(my_cache_backend)

# 2. 图像匹配后端：OpenCV 模板匹配
my_image_matcher = OpenCVImageMatcher(
    image_dir="image_locator",  # 模板图片目录
    threshold=0.8,              # 匹配阈值，范围 0~1
)
ByImageSolution.configure(my_image_matcher)
```

### 自定义 AI 客户端（ByPromptSolution 必须）

`needle` 没有内置通用 LLM 客户端，需要你自己实现 `AIClient` 协议：

```python
from typing import Optional

class MyAIClient:
    def analyze(self, html: str, description: str) -> Optional[str]:
        """根据页面 HTML 和描述返回一个可用的 Playwright locator 表达式。

        返回 None 表示无法给出建议；返回的字符串会被写入 context["fixed_element"]。
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

`needle` 内置了一个基于 Moonshot AI（Kimi）的 `AIClient` 实现，安装 `ai` 依赖后即可使用：

```bash
pip install "needle[ai]"
```

```python
from needle.builtin import ByPromptSolution, KimiClient

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

---

## 装饰器模式

`with_recovery` 可以把自动修复能力注入到任意函数：

```python
from needle import with_recovery

@with_recovery(
    context_extractor=lambda page, locator, **kw: {
        "page": page,
        "locator": locator,
        **kw,
    }
)
def click_element(page, locator):
    page.locator(locator).click()
```

- `context_extractor`：从被装饰函数参数中提取修复上下文，返回 `dict`。
- `reraise_on_failure`：修复失败时是否重新抛出 `RepairFailedException`（默认 `True`）。

---

## 开发与测试

```bash
# 克隆仓库
git clone https://github.com/alucard1123/needle
cd needle

# 创建虚拟环境并安装开发依赖
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 运行测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=needle --cov-report=term-missing
```

---

## 许可证

[MIT](./LICENSE)

## 关于作者
公众号： 中年老吴

<img src="./gongzhonghaoQR.png" width="300" height="300" alt="公众号二维码">

赏老吴杯咖啡：

<img src="./payQR.JPG" width="300" height="400" alt="赏老吴杯咖啡">

找老吴私聊：

<img src="./weixinQR.JPG" width="300" height="400" alt="找老吴私聊">
