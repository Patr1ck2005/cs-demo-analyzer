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
    # K5: the teamplay report reads the same caches — drop it too
    from cs_analyzer.web import teamplay_data

    teamplay_data.invalidate_teamplay()
    # L0: the dashboard highlight feed scans the same caches
    from cs_analyzer.web import feed_data

    feed_data.invalidate_feed()
    # L2: the utility-lab report scans the same caches
    from cs_analyzer.web import utilitylab_data

    utilitylab_data.invalidate_utilitylab()
    # L3: the per-map report scans the same caches
    from cs_analyzer.web import mapdata

    mapdata.invalidate_map_report()
    # L4: the lineups report scans the same caches
    from cs_analyzer.web import lineups_data

    lineups_data.invalidate_lineups()
    # M: the fun-lab report scans the same caches
    from cs_analyzer.web import funlab_data

    funlab_data.invalidate_funlab()
    # N: the style-galaxy report derives from the funlab vectors
    from cs_analyzer.web import style_map

    style_map.invalidate_style_map()
    # S: per-demo in-memory analysis caches key by demo_hash — a re-parse of
    # the same hash (PARSER_VERSION bump) must not keep serving old modules
    from cs_analyzer.web.app import _analysis_cache, _module_cache

    _analysis_cache.clear()
    _module_cache.clear()
    # S: re-arm the background prewarm so "cold again" shows the skeleton
    # instead of blocking the first dashboard request for ~70s. Only when
    # the library WAS warm — tests and cold-start invalidates must not
    # spawn scan threads.
    from cs_analyzer.web import warmup

    if warmup.status().get("ready"):
        warmup.kick()


def _compute() -> AggregateResult:
    from cs_analyzer.web import runtime

    return compute_aggregate(runtime.cache().cache_dir, runtime.settings().analysis)
