"""Shared analysis helpers (Phase I).

round_player_sides: per-round player side ("T"/"CT") derived from live tick
team_num sampled near each round's start. Swap-safe by construction — the
whole-demo-mean approach used before Phase I mislabels everyone after the
halftime swap.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from cs_analyzer.model.parsed_demo import ParsedDemo

# How many ticks after round start to sample team_num over (~8s at 64t).
# Freeze time plus early-round movement is plenty; keeps slices small even on
# 1M-tick demos.
ROUND_SIDE_WINDOW_TICKS = 512


def _side_from_codes(codes: pd.Series) -> str:
    """Majority vote of numeric team codes -> "T" | "CT" | ""."""
    codes = codes.dropna()
    if codes.empty:
        return ""
    counts = codes.value_counts()
    if len(counts) > 1 and counts.iloc[0] == counts.iloc[1]:
        return "T" if float(codes.iloc[0]) < 2.5 else "CT"
    return "T" if counts.index[0] < 2.5 else "CT"


def round_player_sides(demo: ParsedDemo) -> dict[int, dict[str, str]]:
    """{round_number: {steamid: "T"|"CT"}} via majority team_num in
    [start_tick, start_tick + ROUND_SIDE_WINDOW_TICKS].

    Ticks are pre-sorted once by (steamid, tick); each round then reads a
    searchsorted-bounded slice, so cost stays O(rounds x window) instead of a
    full-table scan per round.
    """
    sides: dict[int, dict[str, str]] = {}
    ticks = demo.ticks
    if ticks is None or ticks.empty or not {"steamid", "tick", "team_num"} <= set(ticks.columns):
        return sides
    rounds = demo.regular_rounds
    if not rounds:
        return sides

    t_sorted = ticks.sort_values(["steamid", "tick"], kind="stable")
    tick_vals = t_sorted["tick"].to_numpy()

    for rnd in rounds:
        m: dict[str, str] = {}
        for sid, (i0p, i1p) in _player_row_ranges(t_sorted):
            # searchsorted within this player's contiguous run
            i0 = i0p + int(np.searchsorted(tick_vals[i0p:i1p], rnd.start_tick, side="left"))
            i1 = i0p + int(np.searchsorted(tick_vals[i0p:i1p], rnd.start_tick + ROUND_SIDE_WINDOW_TICKS, side="right"))
            if i0 >= i1:
                continue
            codes = t_sorted["team_num"].iloc[i0:i1]
            s = _side_from_codes(codes)
            if s:
                m[sid] = s
        sides[rnd.number] = m
    return sides


def _player_row_ranges(t_sorted: pd.DataFrame) -> list[tuple[str, tuple[int, int]]]:
    """[(steamid, (row_start, row_end))] for contiguous per-player runs."""
    sid_arr = t_sorted["steamid"].to_numpy()
    boundaries = np.flatnonzero(np.r_[True, sid_arr[1:] != sid_arr[:-1]])
    edges = np.r_[boundaries, len(sid_arr)]
    return [
        (str(sid_arr[b]), (int(b), int(e)))
        for b, e in zip(boundaries, edges[1:])
    ]


def side_of(side_map: dict[int, dict[str, str]], round_number: int, steamid: str) -> str:
    """Side of `steamid` in round N from a round_player_sides map; "" unknown."""
    return side_map.get(round_number, {}).get(steamid, "")
