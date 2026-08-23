"""Probe: compare parse-time roster side vs live per-tick team_num majority.

Read-only over the .cache (no re-parse). For every cached demo and player:
  (a) parse-time Player.team / timeline starting_side
  (b) live majority team_num over regulation first-half ticks (ground truth)
  (c) round-1 freeze-end position cluster -> radar pixel fraction, compared
      with official radar spawn fractions when available (de_mirage).

Verdict per player: MISMATCH when (a) != (b). Exits 0; prints a summary.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from cs_analyzer.config import load_settings
from cs_analyzer.replay.timeline import build_timeline
from cs_analyzer.maps.loader import load_map_or_fallback
from cs_analyzer.web.store import list_demos, load_demo

# Official CS2 radar_info spawn fractions (px/W, px/H) for cross-checking.
OFFICIAL_SPAWNS = {
    "de_mirage": {"CT": (0.28, 0.70), "T": (0.87, 0.36)},
}

MAJORITY_MIN_ROWS = 50


def live_majority(demo, steamid: str, start_tick: int | None, end_tick: int | None) -> str | None:
    ticks = demo.ticks
    if ticks is None or ticks.empty or "team_num" not in ticks.columns:
        return None
    sub = ticks[ticks["steamid"] == steamid]
    if start_tick is not None:
        sub = sub[sub["tick"] >= start_tick]
    if end_tick is not None:
        sub = sub[sub["tick"] <= end_tick]
    sub = sub[sub["team_num"].isin((2.0, 3.0))]
    if len(sub) < MAJORITY_MIN_ROWS:
        return None
    counts = sub["team_num"].value_counts()
    return {2: "T", 3: "CT"}[int(counts.index[0])]


def spawn_fraction(demo, tl, freeze: dict) -> tuple[float, float] | None:
    """Round-1 alive position centroid as a fraction of the radar image."""
    r1 = demo.regular_rounds[0] if demo.regular_rounds else None
    if r1 is None:
        return None
    t0 = freeze.get(r1.number, r1.start_tick)
    i0 = int(np.searchsorted(tl.ticks, t0))
    i1 = min(i0 + 64, len(tl.ticks))  # first second of the round
    if i1 - i0 < 5:
        return None
    xs, ys = tl.xs[i0:i1], tl.ys[i0:i1]
    ok = np.isfinite(xs) & np.isfinite(ys)
    if ok.sum() < 5:
        return None
    res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    b = res.bounds
    fx = (float(np.mean(xs[ok])) - b.min_x) / (b.max_x - b.min_x)
    fy = (1 - (float(np.mean(ys[ok])) - b.min_y) / (b.max_y - b.min_y))
    return fx, fy


def nearest_official(fx: float, fy: float) -> str:
    m = OFFICIAL_SPAWNS.get(current_map)
    if not m:
        return "?"
    d = {side: (fx - ox) ** 2 + (fy - oy) ** 2 for side, (ox, oy) in m.items()}
    return min(d, key=d.get)


current_map = "?"


def main() -> int:
    global current_map
    s = load_settings(None)
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.parser.manager import ParseManager

    manager = ParseManager(cache=DemoCache(s.cache_dir))
    paths = sorted(Path("demos").glob("*.dem")) if Path("demos").is_dir() else []
    if not paths:  # fall back to whatever the cache still indexes
        paths = [Path(e["demo_path"]) for e in list_demos(s.cache_dir)]
    mismatches = 0
    total = 0
    for dem_path in paths:
        demo = manager.parse(dem_path)  # cached or lazy re-parse
        if demo is None:
            continue
        current_map = demo.metadata.map_name
        reg = demo.regular_rounds
        starts = [r.start_tick for r in reg]
        ends = [r.end_tick for r in reg]
        cutoff = starts[0] if starts else None
        half_end = ends[11] if len(ends) >= 12 else (ends[-1] if ends else None)
        print(f"\n== {dem_path.name} ({current_map}) ==")
        from cs_analyzer.replay.timeline import round_freeze_ends

        freeze = round_freeze_ends(demo)
        for p in demo.players:
            try:
                tl = build_timeline(demo, p.steamid)
            except ValueError:
                continue
            total += 1
            live = live_majority(demo, p.steamid, cutoff, half_end)
            frac = spawn_fraction(demo, tl, freeze)
            geo = nearest_official(*frac) if frac else "?"
            flag = ""
            if live is not None and tl.starting_side != live:
                flag = "  <-- MISMATCH"
                mismatches += 1
            pos = f"({frac[0]:.2f},{frac[1]:.2f})" if frac else "-"
            print(f"  {p.name:<16} roster={tl.starting_side:<3} live={live or '-':<4} "
                  f"spawn@{pos} ~{geo}{flag}")
    print(f"\n=== {mismatches} MISMATCH / {total} players ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
