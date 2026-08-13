"""Tests for the cross-demo aggregation module (LTG-2 stage 2)."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis.aggregate import DemoRow, PlayerRow, compute_aggregate
from cs_analyzer.cache import DemoCache

from .conftest import S_ALICE, S_BOB, build_parsed_demo


def _cached_demo(tmp_path):
    ticks = pd.DataFrame(
        {
            "tick": [0, 640, 1280, 1920, 2560, 3200],
            "steamid": [S_ALICE] * 6,
            "X": [0.0, 100.0, 200.0, 300.0, 400.0, 500.0],
            "Y": [0.0] * 6,
            "is_alive": [True] * 6,
            "team_num": [3.0] * 6,
        }
    )
    events = {
        "player_death": pd.DataFrame(
            {
                "tick": [640],
                "attacker_steamid": [S_ALICE],
                "user_steamid": [S_BOB],
                "attacker_name": ["Alice"],
                "user_name": ["Bob"],
                "attacker_team_name": ["CT"],
                "user_team_name": ["T"],
                "weapon": ["ak47"],
            }
        )
    }
    demo = build_parsed_demo(events=events, ticks=ticks)
    cache = DemoCache(tmp_path / "cache")
    cache.save(demo.metadata.demo_hash, demo)
    return cache


def test_compute_aggregate(tmp_path) -> None:
    cache = _cached_demo(tmp_path)
    result = compute_aggregate(cache.cache_dir)
    assert result.total_demos == 1
    assert len(result.players) == 4  # build_demo_data has 4 players
    alice = next(p for p in result.players if p.steamid == S_ALICE)
    assert alice.total_kills >= 1
    assert alice.demo_count == 1
    assert result.demos[0].filename == "synthetic.dem"
    assert result.demos[0].rounds == 2


def test_player_row_properties() -> None:
    row = PlayerRow(
        steamid="1", name="A", total_kills=20, total_deaths=5, total_rounds=10,
        demos=[{"demo": "x.dem", "rounds": 10, "ADR": 85.0, "Rating": 1.1, "KAST": 70.0}],
    )
    assert row.demo_count == 1
    assert row.avg_kpr == 2.0
    assert row.avg_adr == 85.0
    assert row.avg_rating == 1.1
    assert row.avg_kast == 70.0
    # empty demos -> zero averages, no division crash
    empty = PlayerRow(steamid="2", name="B")
    assert empty.avg_kpr == 0.0 and empty.avg_adr == 0.0


def test_demo_row_win_rate() -> None:
    row = DemoRow(
        demo_hash="h", filename="x.dem", map_name="de_mirage", rounds=10,
        t_score=6, ct_score=4, t_win_rate=0.6,
        trend=[{"round": 1, "winner_side": "T", "t_score": 1, "ct_score": 0}],
    )
    assert row.t_win_rate == 0.6
    assert row.trend[0]["winner_side"] == "T"
