"""Tests for the web platform's matplotlib chart renderers (PNG outputs)."""
from __future__ import annotations

from cs_analyzer.analysis.aggregate import AggregateResult, DemoRow, PlayerRow
from cs_analyzer.analysis.preference import PlayerPreference
from cs_analyzer.maps import load_map_or_fallback
from cs_analyzer.render.aggregate_charts import render_aggregate_charts
from cs_analyzer.render.preference_charts import (
    render_heatmap,
    render_style_panel,
    render_utility_map,
)


def test_preference_charts_render(tmp_path) -> None:
    pref = PlayerPreference(
        steamid="1", name="Alice", team="Team 3",
        position_samples=[(0.0, 0.0), (100.0, 50.0), (200.0, 10.0)],
        utility_positions={"smoke": [(50.0, 50.0)]},
        avg_first_engagement_fraction=0.4,
        avg_pitch=2.5,
    )
    map_res = load_map_or_fallback("de_mirage", None)
    h = render_heatmap(pref, map_res, tmp_path / "h.png")
    u = render_utility_map(pref, map_res, tmp_path / "u.png")
    s = render_style_panel(pref, tmp_path / "s.png")
    for p in (h, u, s):
        assert p.exists()
        assert p.stat().st_size > 1000


def test_aggregate_charts_render(tmp_path) -> None:
    result = AggregateResult(
        players=[
            PlayerRow(
                steamid="1", name="A", total_kills=20, total_rounds=10,
                demos=[{"demo": "x.dem", "rounds": 10, "ADR": 80.0, "Rating": 1.1, "KAST": 70.0}],
            )
        ],
        demos=[
            DemoRow(
                demo_hash="h", filename="x.dem", map_name="de_mirage", rounds=10,
                t_score=6, ct_score=4, t_win_rate=0.6,
                trend=[{"round": 1, "winner_side": "T", "t_score": 1, "ct_score": 0}],
            )
        ],
    )
    paths = render_aggregate_charts(result, tmp_path)
    for key in ("player_matrix", "team_win", "trends"):
        assert key in paths, f"missing chart {key}"
        assert (tmp_path / paths[key]).exists()
        assert (tmp_path / paths[key]).stat().st_size > 1000
