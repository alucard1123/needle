"""内置策略的可插拔后端（重依赖通过协议注入 + 懒加载）。

核心库零依赖；内置策略需要的 opencv / AI 客户端等重依赖，统一抽象为
三个协议，运行时由宿主项目注入实现，或回退到本模块提供的「懒加载默认实现」
（在真正被调用时才 ``import``，缺失依赖时给出清晰的安装提示）。
"""

import json
from typing import List, Optional, Protocol, Tuple, runtime_checkable


def _missing(extra: str, pkg: str) -> "RuntimeError":
    return RuntimeError(
        f"该内置策略需要可选依赖 '{pkg}'，请安装：pip install needle[{extra}]，"
        f"或为对应策略注入自定义后端。"
    )


# --------------------------------------------------------------------------- #
# 1. 缓存后端：按 key 查询备选 locator 列表
# --------------------------------------------------------------------------- #
@runtime_checkable
class CacheBackend(Protocol):
    def query(self, key: str) -> Optional[List[str]]:
        """返回该 key 对应的备选 locator 表达式列表（无则 None）。"""
        ...


class PickleDBCacheBackend:
    """基于 JSON 文件的默认缓存后端（已废弃 pickledb）。

    数据文件为 JSON 对象：key 为第一定位符，value 为备用定位符数组。
    文件缺失、为空或解析失败时视为空缓存。
    """

    def __init__(self, db_path: str = "needle_locator_cache.db"):
        self._db_path = db_path
        self._data: Optional[dict] = None

    def _load(self) -> dict:
        if self._data is None:
            try:
                with open(self._db_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"加载缓存后端数据失败（{e}），将使用空缓存")
                loaded = {}
            self._data = loaded if isinstance(loaded, dict) else {}
        return self._data

    def query(self, key: str) -> Optional[List[str]]:
        value = self._load().get(key)
        if isinstance(value, list):
            return value
        return None


# --------------------------------------------------------------------------- #
# 2. 图像匹配后端：在页面截图中定位模板图片，返回中心坐标
# --------------------------------------------------------------------------- #
@runtime_checkable
class ImageMatcher(Protocol):
    def match(self, screenshot: bytes, template_name: str) -> Optional[Tuple[int, int]]:
        """在截图中匹配 ``template_name`` 模板。

        返回的是**截图像素坐标系**中的 (x, y) 中心点坐标；
        调用方（如 ``ByImageSolution``）需要按 ``window.devicePixelRatio``
        换算为页面 CSS 逻辑坐标后再使用。
        """
        ...


class OpenCVImageMatcher:
    """基于 OpenCV 模板匹配的默认实现（懒加载 cv2/numpy）。

    模板图片从 ``image_dir`` 目录下按文件名（不含扩展名）查找。
    """

    def __init__(self, image_dir: str = "image_locator", threshold: float = 0.8):
        self.image_dir = image_dir
        self.threshold = threshold

    def match(self, screenshot: bytes, template_name: str) -> Optional[Tuple[int, int]]:
        try:
            import cv2  # noqa: PLC0415 - 懒加载重依赖
            import numpy as np  # noqa: PLC0415
        except ImportError as e:
            raise _missing("image", "opencv-python") from e

        from pathlib import Path

        tpl_path = None
        root = Path(self.image_dir)
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file() and p.stem == template_name:
                    tpl_path = p
                    break
        if tpl_path is None:
            return None

        screen = cv2.imdecode(np.frombuffer(screenshot, np.uint8), cv2.IMREAD_COLOR)
        template = cv2.imread(str(tpl_path), cv2.IMREAD_COLOR)
        if screen is None or template is None:
            return None

        res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res)
        if max_v < self.threshold:
            return None
        h, w = template.shape[:2]
        return (int(max_l[0] + w / 2), int(max_l[1] + h / 2))


# --------------------------------------------------------------------------- #
# 3. AI 后端：根据 DOM + 自然语言描述给出定位/操作建议
# --------------------------------------------------------------------------- #
@runtime_checkable
class AIClient(Protocol):
    def analyze(self, html: str, description: str) -> Optional[str]:
        """根据页面 HTML 与描述返回一个可用的 locator/操作（失败返回 None）。"""
        ...
