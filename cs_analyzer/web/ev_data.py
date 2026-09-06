"""Memoized cross-demo economy-EV aggregation (Phase V2 决策 EV).

Aggregates EconomyEVModule cells across the whole library into the EV query
table the /match economy tab and the cross-library summary consume.
Uses the T3 shard cache (same pattern as aggregate/feed/funlab_scan): a new
demo costs one demo's module run + a cheap re-merge.
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_cells: list | None = None  # per-demo [(demo_hash, cell dicts)]


def ev_table() -> dict:
    """Merged EV table across the library (memoized)."""
    per_demo = _scan_all()
    agg: dict[tuple, list] = defaultdict(lambda: [0, 0, 0.0])
    total_rounds = 0
    for _h, cells in per_demo:
        for c in cells:
            key = (c["buy"], c["side"], c["score_bin"], c["streak_bin"])
            cell = agg[key]
            cell[0] += c["n"]
            cell[1] += c["wins"]
            if c.get("survived_sum") is not None:
                cell[2] += c["survived_sum"]
            total_rounds = max(total_rounds, c.get("demo_rounds", 0))
    from cs_analyzer.analysis.economy_ev import MIN_SAMPLES

    out = []
    for (buy, side, score_bin, streak_bin), (n, wins, surv) in sorted(agg.items()):
        out.append({
            "buy": buy, "side": side, "score_bin": score_bin, "streak_bin": streak_bin,
            "n": n, "wins": wins,
            "win_rate": round(wins / n, 3) if n >= MIN_SAMPLES else None,
            "survived": round(surv / n, 3) if n >= MIN_SAMPLES and surv else None,
        })
    return {
        "cells": out, "min_samples": MIN_SAMPLES,
        "total_rounds": total_rounds,
        "note": f"决策 EV 表（全库聚合，N<{MIN_SAMPLES} 灰显）· 买法×比分差×连败状态",
    }


def invalidate_ev() -> None:
    global _cells
    with _lock:
        _cells = None


def _scan_all() -> list:
    global _cells
    if _cells is not None:
        return _cells
    from cs_analyzer.analysis.library import cached_demo_hashes, scan_hashes
    from cs_analyzer.web import runtime

    cache_dir = runtime.cache().cache_dir
    pairs = scan_hashes(cache_dir, cached_demo_hashes(cache_dir),
                        lambda d: runtime.analyze_module(d, "economy_ev"))
    entries = []
    for h, result in pairs:
        if result is None:
            continue
        entries.append((h, [{
            "buy": c.buy, "side": c.side, "score_bin": c.score_bin,
            "streak_bin": c.streak_bin, "n": c.n, "wins": c.wins,
            "survived_sum": (c.survived * c.n if c.survived is not None else None),
            "demo_rounds": 0,
        } for c in result.cells]))
    with _lock:
        _cells = entries
        return _cells
