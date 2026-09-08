"""Memoized cross-demo economy-EV aggregation (Phase V2 决策 EV).

Aggregates EconomyEVModule cells across the whole library into the EV query
table the /match economy tab and the cross-library summary consume.
Uses the T3 shard cache (same pattern as aggregate/feed/funlab_scan): a new
demo costs one demo's module run + a cheap re-merge.

Per-demo payload = {"rounds": <that demo's total_rounds>, "cells": [...]}.
``total_rounds`` in the merged table is the SUM across demos (the whole
library's coverage), matching the "本表 N=" caption on the economy tab.
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_cells: list | None = None  # per-demo [{"rounds": int, "cells": [dict]}]


def ev_table() -> dict:
    """Merged EV table across the library (memoized)."""
    per_demo = _scan_all()
    # key -> [n, wins, survived_sum, survived_seen]
    agg: dict[tuple, list] = defaultdict(lambda: [0, 0, 0.0, False])
    total_rounds = 0
    for entry in per_demo:
        total_rounds += entry.get("rounds", 0)
        for c in entry["cells"]:
            key = (c["buy"], c["side"], c["score_bin"], c["streak_bin"])
            cell = agg[key]
            cell[0] += c["n"]
            cell[1] += c["wins"]
            if c.get("survived_sum") is not None:
                cell[2] += c["survived_sum"]
                cell[3] = True
    from cs_analyzer.analysis.economy_ev import MIN_SAMPLES

    out = []
    for (buy, side, score_bin, streak_bin), (n, wins, surv, surv_seen) in sorted(agg.items()):
        # survived_sum == 0 is a legitimate "nobody survived" rate — only an
        # unrecorded field (survived_seen False) suppresses the column.
        out.append({
            "buy": buy, "side": side, "score_bin": score_bin, "streak_bin": streak_bin,
            "n": n, "wins": wins,
            "win_rate": round(wins / n, 3) if n >= MIN_SAMPLES else None,
            "survived": (round(surv / n, 3)
                         if n >= MIN_SAMPLES and surv_seen else None),
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


def _demo_payload(demo) -> dict:
    """Per-demo shard payload: that demo's round count + EV cell dicts."""
    from cs_analyzer.web import runtime

    result = runtime.analyze_module(demo, "economy_ev")
    if result is None:
        return {"rounds": 0, "cells": []}
    return {
        "rounds": result.total_rounds,
        "cells": [{
            "buy": c.buy, "side": c.side, "score_bin": c.score_bin,
            "streak_bin": c.streak_bin, "n": c.n, "wins": c.wins,
            "survived_sum": (c.survived * c.n if c.survived is not None else None),
        } for c in result.cells],
    }


def _scan_all() -> list:
    """Whole-library scan with the T3 shard cache (memoized).

    Thread path via the per-demo module memo (shares results with other
    pages); economy_ev is a light module (no per-tick work), so the process
    pool's spawn overhead would dwarf the gain.
    """
    global _cells
    if _cells is not None:
        return _cells
    from cs_analyzer.analysis.library import scan_hashes
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir
    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("ev_cells", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        pairs = scan_hashes(cache_dir, missing, _demo_payload)
        for h, payload in pairs:
            snapshots.save_shard("ev_cells", runtime.out_dir(), cache_dir, h, payload)
            sharded[h] = payload
    entries = [sharded[h] for h in hashes if h in sharded]
    with _lock:
        _cells = entries
        return _cells
