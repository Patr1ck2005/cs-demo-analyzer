"""Tests for the render layer: radar data merge + rank/is_top computation."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis.basic_stats import BasicStatsResult, PlayerStats
from cs_analyzer.analysis.ratings import PlayerRatings, RatingsResult
from cs_analyzer.render.base import RadarPlayerData, merge_for_radar, merge_for_radar_from_csv

ATTRIBUTES = ["KPR", "Survivals", "ADR", "Headshot%", "FirstKillsPerRound", "Rating Pro"]


def _basic() -> BasicStatsResult:
    return BasicStatsResult(
        module="basic_stats",
        demo_hash="abc",
        players=[
            PlayerStats(
                steamid="1", name="A", team="Team 3",
                KPR=0.9, Survivals=0.4, ADR=80.0, headshot_pct=60.0,
                FirstKillsPerRound=0.1, kills=9, deaths=6, damage=800, rounds=10,
            ),
            PlayerStats(
                steamid="2", name="B", team="Team 2",
                KPR=0.5, Survivals=0.6, ADR=60.0, headshot_pct=20.0,
                FirstKillsPerRound=0.05, kills=5, deaths=4, damage=600, rounds=10,
            ),
        ],
    )


def _ratings() -> RatingsResult:
    return RatingsResult(
        module="ratings",
        demo_hash="abc",
        players=[
            PlayerRatings(steamid="1", name="A", team="Team 3", RWS=10.0, Rating=1.3, Rating_Pro=1.3),
            PlayerRatings(steamid="2", name="B", team="Team 2", RWS=8.0, Rating=1.0, Rating_Pro=1.0),
        ],
    )


def test_merge_for_radar_values() -> None:
    merged = merge_for_radar(_basic(), _ratings(), ATTRIBUTES)
    by_id = {p.ID: p for p in merged}
    assert by_id["A"].Rating_Pro == 1.3
    assert by_id["A"].RWS == 10.0
    assert by_id["A"].Headshot_pct == 60.0
    assert by_id["A"].FirstKillsPerRound == 0.1
    assert by_id["B"].Rating_Pro == 1.0


def test_merge_for_radar_ranks() -> None:
    merged = merge_for_radar(_basic(), _ratings(), ATTRIBUTES)
    a, b = merged[0], merged[1]
    # A is #1 in KPR/ADR/Headshot%/Rating Pro
    assert a.attribute_rank("KPR") == 1
    assert a.attribute_rank("ADR") == 1
    assert a.attribute_rank("Headshot%") == 1
    assert a.attribute_rank("Rating Pro") == 1
    # B is #1 in Survivals
    assert b.attribute_rank("Survivals") == 1
    assert a.attribute_rank("Survivals") == 2
    assert b.attribute_rank("KPR") == 2
    # is_top true for whoever is #1 anywhere
    assert a.is_top and b.is_top


def test_attribute_value_aliases() -> None:
    p = RadarPlayerData(
        ID="A", team="T", KPR=0.8, ADR=70.0, Headshot_pct=40.0, Rating_Pro=1.2, RWS=9.0,
    )
    assert p.attribute_value("Rating Pro") == 1.2
    assert p.attribute_value("Headshot%") == 40.0
    assert p.attribute_value("KPR") == 0.8
    assert p.attribute_value("RWS") == 9.0
    assert p.attribute_value("NoSuchAttr") == 0.0


def test_merge_for_radar_from_csv() -> None:
    df = pd.DataFrame(
        {
            "ID": ["A", "B"],
            "team": ["Team 3", "Team 2"],
            "KPR": [0.9, 0.5],
            "Survivals": [0.4, 0.6],
            "ADR": [80.0, 60.0],
            "Headshot%": [60.0, 20.0],
            "FirstKillsPerRound": [0.1, 0.05],
            "Rating Pro": [1.3, 1.0],
            "RWS": [10.0, 8.0],
        }
    )
    merged = merge_for_radar_from_csv(df, ATTRIBUTES)
    assert merged[0].ID == "A"
    assert merged[0].attribute_rank("KPR") == 1
    assert merged[0].attribute_value("Rating Pro") == 1.3
    assert merged[1].attribute_rank("Survivals") == 1


def test_merge_sorts_players_preserving_order() -> None:
    # merge should preserve basic_stats order (by player), ranks computed independently
    merged = merge_for_radar(_basic(), _ratings(), ATTRIBUTES)
    assert [p.ID for p in merged] == ["A", "B"]
