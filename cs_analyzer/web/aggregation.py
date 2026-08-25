"""Memoized cross-demo aggregation (Phase H M2).

`compute_aggregate` re-runs AnalysisRunner over every cached demo (~seconds
for the local library). The players/matches/compare/dashboard pages all need
it, so the result is computed once and invalidated whenever the cache set
changes (parse job finishes, stale sweep submits, system import).
"""
from __future__ import annotations

import threading

from cs_analyzer.analysis.aggregate import AggregateResult, compute_aggregate

_lock = threading.Lock()
_result: AggregateResult | None = None


def aggregated() -> AggregateResult:
    """Return the memoized aggregate, computing it on first use (single-flight)."""
    global _result
    if _result is None:
        with _lock:
            if _result is None:  # double-checked: only one cold compute
                _result = _compute()
    return _result


def invalidate_aggregate() -> None:
    """Drop the memo. Call whenever the demo cache set may have changed."""
    global _result
    with _lock:
        _result = None


def _compute() -> AggregateResult:
    from cs_analyzer.web.app import _cache, _settings

    return compute_aggregate(_cache().cache_dir, _settings().analysis)
