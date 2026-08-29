"""Tests for Phase I shared analysis helpers (analysis/util.py)."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis.util import round_player_sides, side_of

from .conftest import (
    S_ALICE,
    S_BOB,
    S_CAROL,
    S_DAVE,
    build_demo_data,
    make_round,
)


def _swap_demo() -> "object":
    """12-round demo where everyone swaps sides after round 12 (halftime).

    Alice/Bob: rounds 1-12 CT, rounds 13+ T. Carol/Dave mirror them.
    """
    from cs_analyzer.model.parsed_demo import ParsedDemo
    from cs_analyzer.model.types import MatchMetadata, ProviderKind

    data = build_demo_data()
    data.rounds = [
        make_round(n, (n - 1) * 2560, n * 2560, "CT" if n <= 12 else "T")
        for n in range(1, 15)
    ]
    rows = []
    for n in range(1, 15):
        start = (n - 1) * 2560
        ct_sides = [S_ALICE, S_BOB] if n <= 12 else [S_CAROL, S_DAVE]
        t_sides = [S_CAROL, S_DAVE] if n <= 12 else [S_ALICE, S_BOB]
        for sid in ct_sides:
            rows.append({"tick": start + 10, "steamid": sid, "team_num": 3.0})
        for sid in t_sides:
            rows.append({"tick": start + 10, "steamid": sid, "team_num": 2.0})
    ticks = pd.DataFrame(rows)
    meta = MatchMetadata(
        map_name="de_mirage", demo_path="s.dem", demo_hash="h",
        provider=ProviderKind.UNKNOWN,
        team_a=data.metadata.team_a, team_b=data.metadata.team_b,
    )
    return ParsedDemo(data=data, events={}, ticks=ticks)


def test_round_player_sides_tracks_halftime_swap() -> None:
    """B2: per-round sides must flip at halftime (the old whole-demo mean
    mislabeled every player for half the match)."""
    sides = round_player_sides(_swap_demo())
    assert sides[1][S_ALICE] == "CT"
    assert sides[12][S_ALICE] == "CT"
    assert sides[13][S_ALICE] == "T"
    assert sides[14][S_ALICE] == "T"
    # mirrored
    assert sides[1][S_CAROL] == "T"
    assert sides[13][S_CAROL] == "CT"


def test_round_player_sides_empty_inputs() -> None:
    from cs_analyzer.model.parsed_demo import ParsedDemo

    demo = ParsedDemo(data=build_demo_data(), events={}, ticks=pd.DataFrame())
    assert round_player_sides(demo) == {}


def test_side_of_helper() -> None:
    side_map = {1: {S_ALICE: "CT"}, 2: {S_ALICE: "T"}}
    assert side_of(side_map, 1, S_ALICE) == "CT"
    assert side_of(side_map, 2, S_ALICE) == "T"
    assert side_of(side_map, 3, S_ALICE) == ""       # unknown round
    assert side_of(side_map, 1, S_BOB) == ""         # unknown player


def test_duels_sides_majority_across_rounds() -> None:
    """duels.sides = majority of per-round sides; swap demo -> tie broken by
    later rounds here (7 T vs 7 CT would be a coin toss, so use 9 vs 5)."""
    from cs_analyzer.analysis.duels import DuelsModule
    from cs_analyzer.analysis.base import AnalysisContext
    from cs_analyzer.config import AnalysisConfig

    demo = _swap_demo()
    deaths = pd.DataFrame({
        "tick": [100],
        "attacker_steamid": [S_ALICE],
        "user_steamid": [S_CAROL],
        "attacker_name": ["Alice"],
        "user_name": ["Carol"],
        "weapon": ["ak47"],
    })
    demo.events["player_death"] = deaths
    result = DuelsModule().run(demo, AnalysisContext(AnalysisConfig()))
    # Alice is T in rounds 13-14 only (2), CT in 1-12 (12) -> CT majority
    assert result.sides[S_ALICE] == "CT"
