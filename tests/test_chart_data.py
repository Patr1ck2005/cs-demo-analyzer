"""Tests for the ECharts payload builders (Phase E M6)."""
from __future__ import annotations

from cs_analyzer.analysis.aggregate import AggregateResult, DemoRow, PlayerRow
from cs_analyzer.analysis.basic_stats import BasicStatsResult, PlayerStats
from cs_analyzer.analysis.ratings import PlayerRatings, RatingsResult
from cs_analyzer.web import chart_data

from .conftest import S_ALICE, build_parsed_demo


def _basic(**overrides) -> PlayerStats:
    defaults = dict(
        steamid=S_ALICE, name="Alice", team="Team 3",
        kills=20, deaths=10, assists=5, rounds=24,
        KPR=0.83, Survivals=0.30, ADR=85.0, headshot_pct=48.0,
        FirstKillsPerRound=0.12,
    )
    defaults.update(overrides)
    return PlayerStats(**defaults)


def test_radar_normalizes_into_0_100() -> None:
    basic = BasicStatsResult(module="basic_stats", players=[_basic()])
    ratings = RatingsResult(module="ratings", players=[PlayerRatings(
        steamid=S_ALICE, name="Alice", team="Team 3", RWS=8.0, Rating=1.1, Rating_Pro=1.1,
    )])
    payload = chart_data.radar_payload(basic, ratings)
    assert len(payload["indicators"]) == 6
    s = payload["series"][0]
    assert all(0 <= v <= 100 for v in s["values"])
    # KPR 0.83 in (0.5, 0.9) -> ~82.5
    assert s["values"][0] > 80
    # raw values ride along for tooltips
    assert s["raw"][0] == 0.83


def test_radar_missing_ratings_zeroes() -> None:
    payload = chart_data.radar_payload(BasicStatsResult(module="basic_stats", players=[_basic()]), None)
    s = payload["series"][0]
    assert s["values"][-1] == 0.0  # Rating axis without ratings module
    assert s["rating"] == 0.0


def test_radar_series_sorted_by_rating_desc() -> None:
    a = _basic(steamid="sa", name="A", KPR=0.5)
    b = _basic(steamid="sb", name="B", KPR=0.88)
    ratings = RatingsResult(module="ratings", players=[
        PlayerRatings(steamid="sa", name="A", team="T", Rating=0.9, Rating_Pro=0.9),
        PlayerRatings(steamid="sb", name="B", team="T", Rating=1.2, Rating_Pro=1.2),
    ])
    payload = chart_data.radar_payload(BasicStatsResult(module="basic_stats", players=[a, b]), ratings)
    assert [s["name"] for s in payload["series"]] == ["B", "A"]


def test_position_points_normalized() -> None:
    ticks = __import__("pandas").DataFrame(
        {"tick": [0, 64], "steamid": [S_ALICE] * 2,
         "X": [-3230.0, 1890.0], "Y": [-3407.0, 1713.0],
         "is_alive": [True, True], "team_num": [3.0, 3.0]}
    )
    demo = build_parsed_demo(ticks=ticks)
    from cs_analyzer.analysis.preference import PlayerPreference, PreferenceResult

    pp = PlayerPreference(steamid=S_ALICE, name="Alice", team="Team 3",
                          position_samples=[(-3230.0, -3407.0), (1890.0, 1713.0),
                                            (float("nan"), 0.0)])
    payload = chart_data.player_position_payload(
        PreferenceResult(module="preference", players=[pp]), S_ALICE, demo)
    assert len(payload["points"]) == 2  # NaN sample dropped
    for x, y in payload["points"]:
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
    assert payload["has_map_image"] in (True, False)  # depends on checkout assets


def test_aggregate_payload_shapes() -> None:
    row = PlayerRow(steamid="sa", name="A", demos=[
        {"demo": "x.dem", "Rating": 1.1, "KPR": 0.8, "ADR": 80.0, "KAST": 70.0, "RWS": 7.0},
        {"demo": "y.dem", "Rating": 0.9, "KPR": 0.7, "ADR": 70.0, "KAST": 65.0, "RWS": 6.0},
    ], total_kills=30, total_deaths=20, total_rounds=40)
    result = AggregateResult(
        players=[row],
        demos=[DemoRow(demo_hash="h1", filename="x.dem", map_name="de_mirage",
                       rounds=24, t_score=13, ct_score=11, t_win_rate=0.54, trend=[]),
               DemoRow(demo_hash="h2", filename="y.dem", map_name="de_inferno",
                       rounds=24, t_score=9, ct_score=15, t_win_rate=0.4, trend=[])],
    )
    payload = chart_data.aggregate_payload(result)
    assert payload["matrix"]["players"] == ["A"]
    assert len(payload["matrix"]["values"][0]) == 2
    assert payload["bars"]["names"] == ["A"]
    assert len(payload["trends"]) == 2


def test_style_payload_fields() -> None:
    from cs_analyzer.analysis.preference import PlayerPreference, PreferenceResult

    pp = PlayerPreference(steamid=S_ALICE, name="Alice", team="T",
                          avg_first_engagement_fraction=0.42, engagement_rounds=10,
                          avg_pitch=-3.5, pitch_samples=500,
                          utility_counts={"smoke": 3})
    out = chart_data.player_style_payload(PreferenceResult(module="preference", players=[pp]), S_ALICE)
    assert out["engagement_fraction"] == 0.42
    assert out["utility_counts"] == {"smoke": 3}
