"""Memoized K5 five-stack teamplay report for the compare page.

Loads every cached demo (parse caches only — no .dem re-parse) plus the
memoized aggregate's per-demo ratings. Invalidated together with the
aggregate (aggregation.invalidate_aggregate also drops this memo).
"""
from __future__ import annotations

import threading

from cs_analyzer.analysis.teamplay import build_teamplay_report

_lock = threading.Lock()
_report: dict | None = None


def teamplay_report() -> dict:
    """Return the memoized report, computing it on first use (single-flight)."""
    global _report
    if _report is None:
        with _lock:
            if _report is None:
                _report = _build()
    return _report


def invalidate_teamplay() -> None:
    global _report
    with _lock:
        _report = None


def _build() -> dict:
    from cs_analyzer.web.aggregation import aggregated
    from cs_analyzer.web import runtime

    agg = aggregated()
    demo_ratings: dict[str, dict[str, float]] = {}
    for p in agg.players:
        for d in p.demos:
            demo_ratings.setdefault(d["demo_hash"], {})[p.steamid] = d["Rating"]
    return build_teamplay_report(runtime.cache().cache_dir, demo_ratings=demo_ratings)
