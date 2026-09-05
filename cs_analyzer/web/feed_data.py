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
                from cs_analyzer.web import runtime

                executor = getattr(runtime.settings(), "scan_executor", "thread")
                _feed = _build(executor)
    return _feed


def top_highlights(limit: int) -> list[dict]:
    return all_highlights()[:limit]


def invalidate_feed() -> None:
    global _feed
    with _lock:
        _feed = None


def _feed_from_demo(demo) -> list[dict]:
    """Per-demo highlight payload (module-level: shared by both executors)."""
    from cs_analyzer.web import runtime
    from cs_analyzer.web.chart_data import highlights_payload

    return highlights_payload(runtime.analyze_module(demo, "highlights"))["highlights"]


def _feed_worker(args: tuple[str, str]) -> list[dict] | None:
    """Process-pool worker (T2): loads + runs the highlights module IN the
    child (the per-demo module memo does not cross processes) and ships the
    small highlight dicts back. Fail-soft like the thread path."""
    import logging
    from pathlib import Path

    from cs_analyzer.analysis import AnalysisRunner
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.config import AnalysisConfig
    from cs_analyzer.web.chart_data import highlights_payload

    cache_dir, demo_hash = args
    logger = logging.getLogger(__name__)
    try:
        demo = DemoCache(Path(cache_dir)).load(demo_hash)
        if demo is None:
            return None
        result = AnalysisRunner(AnalysisConfig(enabled_modules=["highlights"])) \
            .run_one(demo, "highlights")
        return highlights_payload(result)["highlights"]
    except Exception:  # noqa: BLE001
        logger.exception("feed worker failed for %s", demo_hash[:12])
        return None


def _build(executor: str = "thread") -> list[dict]:
    """Whole-library highlight feed (T3 shard cache: per-demo payloads are
    cached; a new demo costs one demo's work, not a full rescan)."""
    from cs_analyzer.analysis.library import scan_hashes, scan_hashes_proc
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir
    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("feed", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        if executor == "process":
            pairs = scan_hashes_proc(cache_dir, missing, _feed_worker,
                                     fallback_fn=_feed_from_demo)
        else:
            pairs = scan_hashes(cache_dir, missing, _feed_from_demo)
        for h, payload in pairs:
            snapshots.save_shard("feed", runtime.out_dir(), cache_dir, h, payload)
            sharded[h] = payload
    merged = [item for h in hashes for item in sharded.get(h, [])]
    merged.sort(key=lambda h: (_RANK.get(h["tier"], 99), h["round"]))
    return merged


# ---- T1 snapshot pair (called by web.snapshots under _lock) ----

def _snapshot_payload() -> list[dict] | None:
    return None if _feed is None else list(_feed)


def restore_snapshot(payload: list[dict]) -> None:
    global _feed
    _feed = list(payload)
