"""Tests for the 2D replay renderer: segments, frames, effects, smoke render."""
from __future__ import annotations

import pandas as pd
import pytest

import numpy as np

from cs_analyzer.config import ReplayConfig
from cs_analyzer.replay.timeline import build_timeline
from cs_analyzer.render.effects import EffectManager
from cs_analyzer.render.replay_animation import ReplayAnimationRenderer, build_trail_segments

from .conftest import S_ALICE, S_BOB, build_parsed_demo


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


def test_assign_frame_counts() -> None:
    r = _renderer()
    segs = r._build_segments(_timeline(), "highlights", None, [1], None, tick_rate=64)
    r._assign_frame_counts(segs, tick_rate=64)
    # round 1 = 2560 ticks, speed 1, 30fps -> 2560 / (64*1/30) = 1200 frames
    assert segs[0].n_frames == 1200


def test_utility_throw_reconstruction() -> None:
    """Smoke landing point is exact; throw origin is reconstructed from the
    player's own position flight-seconds before impact."""
    ticks = pd.DataFrame(
        {
            "tick": [0, 1280, 2560],
            "steamid": [S_ALICE] * 3,
            "X": [0.0, 500.0, 1000.0],
            "Y": [0.0, 0.0, 0.0],
            "is_alive": [True] * 3,
            "team_num": [3.0] * 3,
        }
    )
    events = {
        "smokegrenade_detonate": pd.DataFrame(
            {"tick": [2560], "user_steamid": [S_ALICE], "x": [900.0], "y": [0.0]}
        )
    }
    demo = build_parsed_demo(events=events, ticks=ticks)
    tl = build_timeline(demo, S_ALICE)
    e = tl.utilities["smoke"][0]
    # landing point exact; flight 2.0s @ 64 = 128 ticks
    assert (e.x, e.y) == (900.0, 0.0)
    assert e.throw_tick == 2560 - 128
    tx = float(np.interp(e.throw_tick, ticks["tick"], ticks["X"]))
    assert abs(e.throw_x - tx) < 1e-6
    # no expired event -> duration falls back to renderer default (0 here)
    assert e.duration_ticks == 0


def test_utility_real_smoke_duration() -> None:
    """smokegrenade_expired matched by entityid yields the real lifetime."""
    ticks = pd.DataFrame(
        {
            "tick": [0, 500, 1000, 1500, 2500],
            "steamid": [S_ALICE] * 5,
            "X": [0.0, 100.0, 200.0, 300.0, 400.0],
            "Y": [0.0] * 5,
            "is_alive": [True] * 5,
            "team_num": [3.0] * 5,
        }
    )
    dur_s = 22.1
    events = {
        "smokegrenade_detonate": pd.DataFrame(
            {"tick": [1000], "user_steamid": [S_ALICE], "entityid": [42], "x": [150.0], "y": [0.0]}
        ),
        "smokegrenade_expired": pd.DataFrame(
            {"tick": [1000 + int(dur_s * 64)], "user_steamid": [S_ALICE], "entityid": [42], "x": [150.0], "y": [0.0]}
        ),
    }
    demo = build_parsed_demo(events=events, ticks=ticks)
    tl = build_timeline(demo, S_ALICE)
    assert tl.utilities["smoke"][0].duration_ticks == int(dur_s * 64)


def test_utility_duration_rejects_reused_entityid() -> None:
    """Entityid reuse across rounds must not produce absurd durations."""
    ticks = pd.DataFrame(
        {
            "tick": [0, 1000, 2000, 3000, 200000],
            "steamid": [S_ALICE] * 5,
            "X": [0.0, 100.0, 200.0, 300.0, 400.0],
            "Y": [0.0] * 5,
            "is_alive": [True] * 5,
            "team_num": [3.0] * 5,
        }
    )
    events = {
        "smokegrenade_detonate": pd.DataFrame(
            {"tick": [1000], "user_steamid": [S_ALICE], "entityid": [7], "x": [150.0], "y": [0.0]}
        ),
        "smokegrenade_expired": pd.DataFrame(
            {"tick": [200000], "user_steamid": [S_ALICE], "entityid": [7], "x": [150.0], "y": [0.0]}
        ),
    }
    demo = build_parsed_demo(events=events, ticks=ticks)
    tl = build_timeline(demo, S_ALICE)
    assert tl.utilities["smoke"][0].duration_ticks == 0  # outside sane window


def test_effect_projectile_window() -> None:
    """A thrown nade is a projectile active during [throw_tick, land_tick]."""
    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    from cs_analyzer.replay.timeline import Utility

    tl.utilities["smoke"] = [Utility(tick=1000, x=300.0, y=30.0, kind="smoke",
                                     throw_tick=872, throw_x=100.0, throw_y=10.0)]
    from cs_analyzer.maps import load_map_or_fallback

    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    mgr = EffectManager(ReplayConfig(), tl, map_res, tick_rate=64)
    data = mgr._projectiles
    assert data["starts"].size == 1
    assert mgr._projectile_active(data, 871).size == 0  # before throw
    assert mgr._projectile_active(data, 900).size == 1  # in flight
    assert mgr._projectile_active(data, 1000).size == 0  # landed (window ends)


def test_effect_attach_adds_circles_to_axes() -> None:
    """Regression: Circle() artists must be added to the axes or they never
    render. This was the root cause of 'utilities completely absent'."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    from cs_analyzer.maps import load_map_or_fallback

    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    mgr = EffectManager(ReplayConfig(), tl, map_res, tick_rate=64)
    fig, ax = plt.subplots()
    mgr.attach(ax)
    n_patches = len(ax.patches)
    expected = 8 + 5 + 5 + 8 + 4 + 6  # smoke+flash+he+fire+molly+jump_rings
    assert n_patches >= expected
    plt.close(fig)


def _demo_with_freeze_and_death():
    """Round 1 [0,2560] freeze-end 500; Alice dies at 2000."""
    ticks = pd.DataFrame(
        {
            "tick": list(range(0, 5120, 64)),
            "steamid": [S_ALICE] * 80,
            "X": [float(i) for i in range(80)],
            "Y": [0.0] * 80,
            "is_alive": [True] * 80,
            "team_num": [3.0] * 80,
        }
    )
    events = {
        "player_death": pd.DataFrame(
            {"tick": [2000], "user_steamid": [S_ALICE], "attacker_steamid": [S_BOB],
             "user_name": ["Alice"], "attacker_name": ["Bob"]}
        ),
        "round_freeze_end": pd.DataFrame({"tick": [500, 2660]}),
    }
    return build_parsed_demo(events=events, ticks=ticks)


def test_alive_window_trims_freeze_and_death() -> None:
    demo = _demo_with_freeze_and_death()
    tl = _timeline(demo)
    from cs_analyzer.replay.timeline import round_freeze_ends

    freeze = round_freeze_ends(demo)
    rnd = demo.regular_rounds[0]
    start, end = tl.alive_window(rnd, freeze.get(rnd.number))
    assert start == 500   # prep/freeze time trimmed
    assert end == 2000    # post-death time trimmed (death tick inclusive)


def test_full_windows_freeze_death_trim() -> None:
    demo = _demo_with_freeze_and_death()
    r = ReplayAnimationRenderer(ReplayConfig(), demo)
    tl = _timeline(demo)
    wins = r._full_windows(tl)
    by_round = {n: (s, e) for n, s, e in wins}
    assert by_round[1] == (500, 2000)  # freeze + death trimmed
    # round 2 has no Alice death -> whole [freeze, end]
    assert by_round[2][0] == 2660
    assert by_round[2][1] == 5120


def test_opening_windows_clamp_to_30s() -> None:
    demo = _demo_with_freeze_and_death()
    r = ReplayAnimationRenderer(ReplayConfig(), demo)
    tl = _timeline(demo)
    wins = r._opening_windows(tl, opening=30.0, tick_rate=64)
    by_round = {n: (s, e) for n, s, e in wins}
    # round 1: freeze 500 -> +30s(1920 ticks) = 2420, but death at 2000 clamps
    assert by_round[1] == (500, 2000)
    # round 2: freeze 2660 -> +1920 = 4580 < 5120
    assert by_round[2] == (2660, 4580)


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


def test_trail_segments_break_at_teleport() -> None:
    wx = np.array([0.0, 10.0, 20.0, 30.0])
    wy = np.zeros(4)
    segs = build_trail_segments(wx, wy, break_distance=50.0)
    assert len(segs) == 3  # continuous path fully connected

    # A teleport in the middle must not be connected across.
    wx2 = np.array([0.0, 10.0, 2000.0, 2010.0])
    segs2 = build_trail_segments(wx2, wy, break_distance=50.0)
    assert len(segs2) == 2  # pairs 0-1 and 2-3; pair 1-2 spans the jump
    for (x0, _), (x1, _) in segs2:
        assert abs(x1 - x0) < 50.0  # no segment crosses the teleport


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
