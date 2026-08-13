"""Tests for the static radar chart renderer (web platform)."""
from __future__ import annotations

from cs_analyzer.config import RadarChartConfig
from cs_analyzer.render.base import RadarPlayerData
from cs_analyzer.render.radar_static import render_radar_static


def test_render_radar_static(tmp_path) -> None:
    p = RadarPlayerData(
        ID="Alice", team="Team 3",
        KPR=0.8, Survivals=0.3, ADR=85.0, Headshot_pct=45.0,
        FirstKillsPerRound=0.1, Rating_Pro=1.2,
    )
    out = tmp_path / "radar.png"
    result = render_radar_static(p, RadarChartConfig(), out)
    assert result.exists()
    assert result.stat().st_size > 1000


def test_render_radar_static_top_highlight(tmp_path) -> None:
    p = RadarPlayerData(
        ID="Bob", team="Team 2",
        KPR=0.9, Survivals=0.3, ADR=90.0, Headshot_pct=40.0,
        FirstKillsPerRound=0.12, Rating_Pro=1.3,
        is_top=True,
    )
    out = tmp_path / "radar_top.png"
    render_radar_static(p, RadarChartConfig(), out)
    assert out.exists()
