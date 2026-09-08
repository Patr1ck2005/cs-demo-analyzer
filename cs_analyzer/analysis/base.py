"""Analysis module protocol and shared context."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from cs_analyzer.config import AnalysisConfig
from cs_analyzer.model.parsed_demo import ParsedDemo


class AnalysisResult(BaseModel):
    """Base for all analysis outputs. JSON-serializable for caching."""

    module: str
    demo_hash: str = ""


class AnalysisContext:
    """Shared state passed to each module: config + results from dependencies."""

    def __init__(self, config: AnalysisConfig) -> None:
        self.config = config
        self.results: dict[str, AnalysisResult] = {}

    def put(self, result: AnalysisResult) -> None:
        self.results[result.module] = result

    def get(self, module_name: str) -> AnalysisResult | None:
        return self.results.get(module_name)

    def require(self, module_name: str) -> AnalysisResult:
        result = self.results.get(module_name)
        if result is None:
            raise RuntimeError(
                f"Module '{module_name}' result not available. "
                f"Ensure it runs before dependents."
            )
        return result


class AnalysisModule(ABC):
    """Base class for analysis modules. Subclass and register with @register_module."""

    name: ClassVar[str]
    requires: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        """Compute the result. May read ctx.get(dep) for dependencies."""

    def options(self, ctx: AnalysisContext) -> dict[str, Any]:
        """Per-module options from config.module_options."""
        return dict(ctx.config.module_options.get(self.name, {}))


_REGISTRY: dict[str, type[AnalysisModule]] = {}


def register_module(cls: type[AnalysisModule]) -> type[AnalysisModule]:
    """Decorator to register an AnalysisModule subclass."""
    if not hasattr(cls, "name") or not cls.name:
        raise ValueError(f"{cls.__name__} must define a non-empty `name` ClassVar")
    _REGISTRY[cls.name] = cls
    return cls


def get_module(name: str) -> AnalysisModule:
    """Instantiate a registered module by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown analysis module '{name}'. Registered: {list(_REGISTRY)}")
    return _REGISTRY[name]()


def all_modules() -> dict[str, type[AnalysisModule]]:
    return dict(_REGISTRY)
