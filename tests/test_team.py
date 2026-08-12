"""Tests for the 10-player team replay renderer."""
from __future__ import annotations

import pandas as pd
import pytest

from cs_analyzer.config import ReplayConfig
from cs_analyzer.render.team_animation import TeamReplayRenderer

from .conftest import S_ALICE, S_BOB, build_parsed_demo


def _team_demo():
    """Two rounds [0,2560]/[2560,5120]; Alice + Bob tracked; freeze ends 500/2660."""
    alice_ticks = list(range(0, 2560, 128)) + list(range(2560, 5120, 128))  # 40 ticks
    ticks = pd.DataFrame(
        {
            "tick": alice_ticks + alice_ticks,
            "steamid": [S_ALICE] * 40 + [S_BOB] * 40,
            "X": [float(i) for i in range(40)] + [float(i) for i in range(40)],
            "Y": [0.0] * 80,
            "is_alive": [True] * 80,
            "team_num": [3.0] * 80,
        }
    )
    events = {"round_freeze_end": pd.DataFrame({"tick": [500, 2660]})}
    return build_parsed_demo(events=events, ticks=ticks)


def test_team_loads_players_and_aggregates() -> None:
    r = TeamReplayRenderer(ReplayConfig(), _team_demo())
    assert len(r.timelines) == 2
    assert {tl.player.steamid for tl in r.timelines} == {S_ALICE, S_BOB}
    assert len(r.colors) == 2


def test_team_segments_freeze_trim() -> None:
    r = TeamReplayRenderer(ReplayConfig(), _team_demo())
    segs = r._segments(None, speed=5.0)
    assert len(segs) == 2
    assert segs[0][1] == 500  # prep/freeze trimmed
    assert segs[1][1] == 2660


def test_team_segments_round_filter() -> None:
    r = TeamReplayRenderer(ReplayConfig(), _team_demo())
    segs = r._segments([2], speed=5.0)
    assert [s[0] for s in segs] == [2]


@pytest.mark.skipif(
    __import__("cs_analyzer.utils.ffmpeg", fromlist=["find_ffmpeg"]).find_ffmpeg() is None,
    reason="ffmpeg not available",
)
def test_team_render_produces_video(tmp_path) -> None:
    cfg = ReplayConfig(width=320, height=180, fps=10, dpi=50, speed_team=40.0)
    r = TeamReplayRenderer(cfg, _team_demo())
    out = r.render(tmp_path / "team.mp4", rounds=[1], speed=40.0)
    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(
    __import__("cs_analyzer.utils.ffmpeg", fromlist=["find_ffmpeg"]).find_ffmpeg() is None,
    reason="ffmpeg not available",
)
def test_team_overlay_render_produces_video(tmp_path) -> None:
    cfg = ReplayConfig(width=320, height=180, fps=10, dpi=50)
    r = TeamReplayRenderer(cfg, _team_demo())
    out = r.render_overlay(tmp_path / "team_overlay.mp4", per_round=True, speed=40.0)
    assert out.exists()
    assert out.stat().st_size > 0
