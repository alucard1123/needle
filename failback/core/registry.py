"""SolutionRegistry —— 修复策略注册中心（零依赖）。

负责收集所有 :class:`~failback.core.solution.FailBackSolution` 子类、按 ``PRIORITY``
排队，并在修复时把它们组装成一条责任链。

发现策略的两种途径：

1. 显式注册 —— 调用 :meth:`register`（或顶层便捷函数 ``register_solution``）。
   这是库的推荐用法，零依赖且行为确定。
2. 包扫描 —— 调用 :meth:`scan` 并传入一个包名/模块对象，自动收集其中的子类。
   主要用于「内置策略包」或希望约定优于配置的项目。
"""

from typing import Callable, List, Optional, Type

from failback.core.solution import FailBackSolution


class SolutionRegistry:
    # 已显式注册的策略类，始终按 PRIORITY 升序维护。
    _solutions: List[Type[FailBackSolution]] = []

    @classmethod
    def register(cls, solution_class: Type[FailBackSolution]) -> Type[FailBackSolution]:
        """注册一个策略类（可作为装饰器使用）。重复注册会被忽略。"""
        if not (isinstance(solution_class, type) and issubclass(solution_class, FailBackSolution)):
            raise TypeError(f"{solution_class!r} 不是 FailBackSolution 的子类")
        if solution_class is FailBackSolution:
            raise TypeError("不能注册抽象基类 FailBackSolution 本身")
        if solution_class not in cls._solutions:
            cls._solutions.append(solution_class)
            cls._solutions.sort(key=lambda c: c.PRIORITY)
        return solution_class

    @classmethod
    def unregister(cls, solution_class: Type[FailBackSolution]) -> None:
        """注销一个策略类（主要用于测试或运行期裁剪）。"""
        if solution_class in cls._solutions:
            cls._solutions.remove(solution_class)

    @classmethod
    def clear(cls) -> None:
        """清空所有已注册策略。"""
        cls._solutions = []

    @classmethod
    def registered(cls) -> List[Type[FailBackSolution]]:
        """返回当前已注册策略的副本（按优先级排序）。"""
        return cls._solutions.copy()

    @classmethod
    def scan(cls, module, *, register: bool = True) -> List[Type[FailBackSolution]]:
        """扫描指定包/模块，收集其中所有可实例化的 FailBackSolution 子类。

        ``module`` 可以是模块对象或可导入的模块/包路径字符串。子包会被递归导入。
        ``register=True`` 时把发现的类一并注册到全局表。
        """
        import importlib
        import inspect
        import pkgutil

        if isinstance(module, str):
            module = importlib.import_module(module)

        # 若是包，递归导入子模块，确保其中定义的类被加载。
        if hasattr(module, "__path__"):
            for _finder, mod_name, _ispkg in pkgutil.walk_packages(
                module.__path__, module.__name__ + "."
            ):
                try:
                    importlib.import_module(mod_name)
                except Exception:  # noqa: BLE001 - 单个子模块导入失败不应中断扫描
                    continue

        found: List[Type[FailBackSolution]] = []
        seen = set()
        # 同时检查包对象本身及其所有已导入子模块的成员。
        import sys

        candidates = [module]
        prefix = module.__name__ + "."
        candidates += [m for name, m in list(sys.modules.items()) if name.startswith(prefix) and m]

        for mod in candidates:
            for _name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, FailBackSolution)
                    and obj is not FailBackSolution
                    and not inspect.isabstract(obj)
                    and obj not in seen
                ):
                    seen.add(obj)
                    found.append(obj)

        found.sort(key=lambda c: c.PRIORITY)
        if register:
            for c in found:
                cls.register(c)
        return found

    @classmethod
    def create_chain(
        cls,
        context: dict,
        filter_func: Optional[Callable[[Type[FailBackSolution]], bool]] = None,
        include_builtins: bool = True,
    ) -> Optional[FailBackSolution]:
        """把已注册策略按优先级组装成一条责任链，返回链头。

        ``filter_func`` 可选，用于在建链前筛掉部分策略类。
        ``include_builtins`` 为 True（默认）时自动扫描并注册 ``failback.builtin``
        中的内置策略。无可用策略时返回 ``None``。
        """
        if include_builtins:
            cls.scan("failback.builtin", register=True)
        solutions = cls.registered()
        if filter_func:
            solutions = [s for s in solutions if filter_func(s)]
        if not solutions:
            return None

        head = solutions[0](context)
        current = head
        for sol_class in solutions[1:]:
            current = current.set_next(sol_class(context))
        return head
