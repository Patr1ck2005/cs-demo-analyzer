"""Tests for the parse-coverage scanner and report (LTG-3)."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.coverage import (
    DemoCoverage,
    PlayerCoverage,
    _player_position_stats,
    _score,
    render_coverage_report,
    scan_demo,
)

from .conftest import S_ALICE, S_BOB, build_parsed_demo


def _ticks():
    # Alice has full positions; Bob is present in ticks but all-NaN (Team 0 style).
    return pd.DataFrame(
        {
            "tick": [0, 640, 1280] * 2,
            "steamid": [S_ALICE, S_ALICE, S_ALICE, S_BOB, S_BOB, S_BOB],
            "X": [0.0, 100.0, 200.0, float("nan"), float("nan"), float("nan")],
            "Y": [0.0, 10.0, 20.0, float("nan"), float("nan"), float("nan")],
            "is_alive": [True, True, True, False, False, False],
            "team_num": [3.0, 3.0, 3.0, float("nan"), float("nan"), float("nan")],
        }
    )


def _coverage() -> DemoCoverage:
    return DemoCoverage(
        path="x.dem",
        demo_hash="h",
        map_name="de_mirage",
        provider="perfect_world",
        num_rounds=24,
        regular_rounds=24,
        t_score=13,
        ct_score=11,
        players=[
            PlayerCoverage(
                steamid="1", name="A", team="Team 2", has_position=True,
                position_ratio=1.0, replayable=True, team_zero=False,
            ),
            PlayerCoverage(
                steamid="2", name="B", team="Team 0", has_position=False,
                position_ratio=0.0, replayable=False, team_zero=True,
            ),
        ],
        event_tables=["player_death", "weapon_fire"],
    )


def test_position_stats_detects_missing_data() -> None:
    demo = build_parsed_demo(ticks=_ticks())
    pos = _player_position_stats(demo)
    assert pos[S_ALICE] == (True, 1.0)
    assert pos[S_BOB] == (False, 0.0)


def test_team_label() -> None:
    assert (
        PlayerCoverage(steamid="1", name="a", team="Team 2", has_position=True,
                       position_ratio=1.0, replayable=True, team_zero=False).team_label
        == "T"
    )
    assert (
        PlayerCoverage(steamid="1", name="a", team="Team 3", has_position=True,
                       position_ratio=1.0, replayable=True, team_zero=False).team_label
        == "CT"
    )
    assert (
        PlayerCoverage(steamid="1", name="a", team="Team 0", has_position=False,
                       position_ratio=0.0, replayable=False, team_zero=True).team_label
        == "Team 0"
    )


def test_score_from_rounds() -> None:
    assert _score(build_parsed_demo()) == (1, 1)


def test_demo_coverage_properties() -> None:
    dc = _coverage()
    assert len(dc.team_zero_players) == 1
    assert dc.team_zero_players[0].name == "B"
    assert len(dc.replayable_players) == 1
    assert dc.replayable_players[0].name == "A"


def test_render_coverage_report(tmp_path) -> None:
    out = tmp_path / "coverage.html"
    result = render_coverage_report([_coverage()], out)
    assert result.exists()
    html = out.read_text(encoding="utf-8")
    assert "de_mirage" in html
    assert "调查结论" in html
    assert "可回放" in html
    assert "A" in html  # player rendered


def test_scan_demo_real(real_demo_path) -> None:
    demo = scan_demo(real_demo_path)
    assert demo.status == "ok"
    assert demo.map_name
    assert demo.players
    assert 0 <= len(demo.replayable_players) <= len(demo.players)
