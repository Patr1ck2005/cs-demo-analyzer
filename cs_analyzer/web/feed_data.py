"""Memoized dashboard highlight feed (Phase L0).

The dashboard used to run this scan synchronously on every request — the
largest chunk of the ~70s cold start (~50s here vs ~17s for the aggregate,
because the highlights module is heavier than basic stats). Now it is
computed once, prewarmed at startup by web.warmup, and invalidated together
with the aggregate (aggregation.invalidate_aggregate drops this memo too).
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_feed: list[dict] | None = None

_RANK = {"ace": 0, "k4": 1, "1v4": 2, "k3": 3, "1v3": 4, "k2": 5, "1v2": 6}


def all_highlights() -> list[dict]:
    """Full global highlight feed, best-first (single-flight memo)."""
    global _feed
    if _feed is None:
        with _lock:
            if _feed is None:
                _feed = _build()
    return _feed


def top_highlights(limit: int) -> list[dict]:
    return all_highlights()[:limit]


def invalidate_feed() -> None:
    global _feed
    with _lock:
        _feed = None


def _build() -> list[dict]:
    from cs_analyzer.analysis.library import scan_demos
    from cs_analyzer.web import runtime
    from cs_analyzer.web.chart_data import highlights_payload

    per_demo = scan_demos(
        runtime.cache().cache_dir,
        lambda demo: highlights_payload(runtime.analyze_module(demo, "highlights"))["highlights"],
    )
    merged = [h for lst in per_demo for h in lst]
    merged.sort(key=lambda h: (_RANK.get(h["tier"], 99), h["round"]))
    return merged
