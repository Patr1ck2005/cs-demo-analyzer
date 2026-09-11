"""Memoized cross-demo aggregation (Phase H M2).

`compute_aggregate` re-runs AnalysisRunner over every cached demo (~seconds
for the local library). The players/matches/compare/dashboard pages all need
it, so the result is computed once and invalidated whenever the cache set
changes (parse job finishes, stale sweep submits, system import).
"""
from __future__ import annotations

import threading
from dataclasses import asdict

from cs_analyzer.analysis.aggregate import AggregateResult, DemoRow, PlayerRow

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


def aggregated_peek() -> AggregateResult | None:
    """Read-only variant for request paths (R3-F3): the memo only when warm.

    Never computes — a cold caller gets None and must answer 503 instead of
    synchronously scanning the whole library (U1 lesson; S3-B2 precedent for
    aim/loss/duel)."""
    with _lock:
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
    # V2: the economy-EV table aggregates the same cache set
    from cs_analyzer.web import ev_data

    ev_data.invalidate_ev()
    # R3/R5: research memos aggregate the same cache set
    from cs_analyzer.web import aim_data, loss_data

    aim_data.invalidate_aimsci()
    loss_data.invalidate_lossattr()
    # X: the win-probability LOO shards aggregate the same cache set
    from cs_analyzer.web import winprob_loo

    winprob_loo.invalidate_winloo()
    # Round 2: the duel-model shards aggregate the same cache set
    from cs_analyzer.web import duel_data

    duel_data.invalidate_duelmo()
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
    # T3: shard GC — demo renames/re-parses/code bumps leave files the next
    # scan will never read again. Fail-soft and cheap (a directory walk).
    try:
        from cs_analyzer.web import runtime, snapshots

        snapshots.gc_shards(runtime.out_dir(), runtime.cache().cache_dir)
    except Exception:  # noqa: BLE001 — hygiene must never break invalidation
        pass


def _compute() -> AggregateResult:
    """Whole-library aggregate with the T3 shard cache: per-demo work runs
    only for demos whose (code, model) pair has no valid shard; hits are
    reassembled and merged exactly like a fresh compute, so a NEW demo costs
    one demo's work, not a full-library rescan."""
    from cs_analyzer.analysis.aggregate import _aggregate_worker, merge_aggregate_shards
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir

    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("aggregate", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        executor = getattr(runtime.settings(), "scan_executor", "thread")
        if executor == "process":
            from cs_analyzer.analysis.library import scan_hashes_proc

            pairs = scan_hashes_proc(cache_dir, missing, _aggregate_worker,
                                     fallback_fn=_aggregate_from_demo_thread)
        else:
            from cs_analyzer.analysis import AnalysisRunner
            from cs_analyzer.analysis.aggregate import _aggregate_shard_from_demo
            from cs_analyzer.analysis.library import scan_hashes
            from cs_analyzer.config import AnalysisConfig

            runner = AnalysisRunner(AnalysisConfig(enabled_modules=["basic_stats",
                                                                    "ratings"]))
            pairs = scan_hashes(cache_dir, missing,
                                lambda d: _aggregate_shard_from_demo(d, runner))
        for h, payload in pairs:
            snapshots.save_shard("aggregate", runtime.out_dir(), cache_dir, h, payload)
            sharded[h] = payload

    # sorted-hash order (identical to the old serial contract)
    return merge_aggregate_shards(sharded[h] for h in hashes if h in sharded)


def _aggregate_from_demo_thread(demo):
    """Thread-mode shard fn for the process fallback path (fallback_fn of
    scan_hashes_proc must produce the SAME dict shape as the worker)."""
    from cs_analyzer.analysis.aggregate import _aggregate_shard_from_demo

    return _aggregate_shard_from_demo(demo)


# ---- T1 snapshot pair (called by web.snapshots under _lock) ----

def _snapshot_payload() -> dict | None:
    """JSON-able snapshot of the current aggregate, or None when cold.

    AggregateResult is intentionally cheap to rebuild: PlayerRow/DemoRow
    properties are all DERIVED from the additive totals, so asdict() of the
    plain fields loses nothing.
    """
    if _result is None:
        return None
    return {
        "players": [asdict(p) for p in _result.players],
        "demos": [asdict(d) for d in _result.demos],
    }


def restore_snapshot(payload: dict) -> None:
    """Seed the memo from a snapshot payload (fail-loud: snapshots.restore_all
    catches and falls back to a recompute)."""
    global _result
    players = [PlayerRow(**p) for p in payload.get("players", [])]
    demos = [DemoRow(**d) for d in payload.get("demos", [])]
    _result = AggregateResult(players=players, demos=demos)
