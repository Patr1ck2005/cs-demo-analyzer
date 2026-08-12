"""Tests for the 2D replay renderer: segments, frames, effects, smoke render."""
from __future__ import annotations

import pandas as pd
import pytest

from cs_analyzer.config import ReplayConfig
from cs_analyzer.replay.timeline import build_timeline
from cs_analyzer.render.effects import EffectManager
from cs_analyzer.render.replay_animation import ReplayAnimationRenderer

from .conftest import S_ALICE, build_parsed_demo


def _demo_with_round_ticks():
    """2-round demo (round 1 = [0,2560], round 2 = [2560,5120]) with Alice ticks."""
    ticks = pd.DataFrame(
        {
            "tick": [0, 640, 1280, 1920, 2560, 2560, 3200, 3840, 4480, 5120],
            "steamid": [S_ALICE] * 10,
            "X": [0.0, 100.0, 200.0, 300.0, 400.0, 400.0, 500.0, 600.0, 700.0, 800.0],
            "Y": [0.0, 10.0, 20.0, 30.0, 40.0, 40.0, 50.0, 60.0, 70.0, 80.0],
            "is_alive": [True] * 10,
            "team_num": [3.0] * 5 + [2.0] * 5,  # side swaps at halftime
        }
    )
    return build_parsed_demo(ticks=ticks)


def _renderer():
    return ReplayAnimationRenderer(ReplayConfig(), _demo_with_round_ticks())


def _timeline(demo=None):
    return build_timeline(demo or _demo_with_round_ticks(), S_ALICE)


def test_build_segments_all_mode() -> None:
    r = _renderer()
    segs = r._build_segments(_timeline(), "all", None, None, None, tick_rate=64)
    assert [s.start_tick for s in segs] == [0, 2560]
    assert segs[0].speed == ReplayConfig().speed_full


def test_build_segments_highlights_filter() -> None:
    r = _renderer()
    segs = r._build_segments(_timeline(), "highlights", None, [2], None, tick_rate=64)
    assert len(segs) == 1
    assert segs[0].start_tick == 2560
    assert segs[0].speed == ReplayConfig().speed_highlight


def test_build_segments_montage_clamps_to_round_duration() -> None:
    r = _renderer()
    # opening 1s @ 64 tick = 64 ticks, well under round duration 2560
    segs = r._build_segments(_timeline(), "montage", None, None, opening=1.0, tick_rate=64)
    assert len(segs) == 2
    for s in segs:
        assert s.end_tick - s.start_tick == 64
        assert s.speed == ReplayConfig().speed_montage


def test_assign_frame_counts() -> None:
    r = _renderer()
    segs = r._build_segments(_timeline(), "highlights", None, [1], None, tick_rate=64)
    r._assign_frame_counts(segs, tick_rate=64)
    # round 1 = 2560 ticks, speed 1, 30fps -> 2560 / (64*1/30) = 1200 frames
    assert segs[0].n_frames == 1200


def test_effect_active_window() -> None:
    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    cfg = ReplayConfig()
    # Attach a smoke event at tick 100 (impact at world coords within bounds).
    tl.utilities["smoke"] = [__import__("cs_analyzer.replay.timeline", fromlist=["Event"]).Event(tick=100, x=150.0, y=15.0)]
    from cs_analyzer.maps import load_map_or_fallback

    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    mgr = EffectManager(cfg, tl, map_res, tick_rate=64)
    data = mgr._smoke
    # Active at tick 100 (start); active during smoke_duration; inactive before.
    assert mgr._active_idx(data, 50).size == 0
    assert mgr._active_idx(data, 100).size == 1
    assert mgr._active_idx(data, 100 + int(18 * 64) // 2).size == 1


@pytest.mark.skipif(
    __import__("cs_analyzer.utils.ffmpeg", fromlist=["find_ffmpeg"]).find_ffmpeg() is None,
    reason="ffmpeg not available",
)
def test_render_smoke_short_video(tmp_path) -> None:
    """Rendering one short segment produces a non-empty MP4 (Agg + ffmpeg)."""
    cfg = ReplayConfig(width=320, height=180, fps=10, dpi=50)
    r = ReplayAnimationRenderer(cfg, _demo_with_round_ticks())
    out = tmp_path / "smoke.mp4"
    result = r.render_player(S_ALICE, out, mode="highlights", speed=30.0, rounds=[1])
    assert result.exists()
    assert result.stat().st_size > 0
