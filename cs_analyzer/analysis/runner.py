"""Analysis runner: executes modules in dependency order, shares context."""
from __future__ import annotations

import logging

from cs_analyzer.analysis.base import (
    AnalysisContext,
    AnalysisResult,
    all_modules,
    get_module,
)
from cs_analyzer.config import AnalysisConfig
from cs_analyzer.model.parsed_demo import ParsedDemo

# Import modules so their @register_module decorators run on import.
import cs_analyzer.analysis.basic_stats  # noqa: F401
import cs_analyzer.analysis.preference  # noqa: F401
import cs_analyzer.analysis.ratings  # noqa: F401
import cs_analyzer.analysis.ratings21  # noqa: F401  # Phase U1
import cs_analyzer.analysis.weapon_timeline  # noqa: F401  # Phase U2
import cs_analyzer.analysis.win_probability  # noqa: F401  # Phase V1
import cs_analyzer.analysis.economy_ev  # noqa: F401  # Phase V2
import cs_analyzer.analysis.duels  # noqa: F401
import cs_analyzer.analysis.economy  # noqa: F401
import cs_analyzer.analysis.utility_effect  # noqa: F401
import cs_analyzer.analysis.routes  # noqa: F401
import cs_analyzer.analysis.highlights  # noqa: F401
# Phase I deepening modules (lazy-fetched per page via _analyze_module)
import cs_analyzer.analysis.kill_context  # noqa: F401
import cs_analyzer.analysis.hitgroups  # noqa: F401
import cs_analyzer.analysis.aim  # noqa: F401
import cs_analyzer.analysis.postplant  # noqa: F401
import cs_analyzer.analysis.weapon_splits  # noqa: F401
# Phase M fun metrics (quadrant lab)
import cs_analyzer.analysis.funlab  # noqa: F401
# Phase R research modules (must be import-registered or run_one raises
# "failed to produce a result" — U1 lesson)
import cs_analyzer.analysis.aim_science  # noqa: F401  # R3 枪法科学
import cs_analyzer.analysis.loss_attribution  # noqa: F401  # R5 失利归因

logger = logging.getLogger(__name__)


class AnalysisRunner:
    """Runs analysis modules against a parsed demo in dependency order.

    A single AnalysisContext is shared across modules, so a module can read
    results from its declared dependencies via ctx.require().
    """

    def __init__(self, config: AnalysisConfig | None = None) -> None:
        self.config = config or AnalysisConfig()

    def run(self, demo: ParsedDemo, modules: list[str] | None = None) -> dict[str, AnalysisResult]:
        """Run the given modules (or config.enabled_modules) in dependency order."""
        module_names = list(modules or self.config.enabled_modules)
        ordered = self._topological_sort(module_names)
        ctx = AnalysisContext(self.config)

        for name in ordered:
            try:
                module = get_module(name)
            except KeyError as exc:
                logger.warning("%s", exc)
                continue
            logger.debug("running analysis module: %s", name)
            result = module.run(demo, ctx)
            ctx.put(result)

        return ctx.results

    def run_one(self, demo: ParsedDemo, module_name: str) -> AnalysisResult:
        """Run a single module plus its dependencies."""
        results = self.run(demo, [module_name])
        if module_name not in results:
            raise RuntimeError(f"Module '{module_name}' failed to produce a result")
        return results[module_name]

    @staticmethod
    def _topological_sort(module_names: list[str]) -> list[str]:
        """Order modules so dependencies come first."""
        visited: set[str] = set()
        ordered: list[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            cls = all_modules().get(name)
            if cls is None:
                logger.warning("module '%s' not registered, skipping", name)
                return
            for dep in cls.requires:
                visit(dep)
            ordered.append(name)

        for name in module_names:
            visit(name)
        return ordered
