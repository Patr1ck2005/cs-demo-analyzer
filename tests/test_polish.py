"""Tests for STG-1 replay polish: shot z-order, HUD feed/color, opening config."""
from __future__ import annotations

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from cs_analyzer.config import ReplayConfig
from cs_analyzer.maps import load_map_or_fallback
from cs_analyzer.render.effects import EffectManager
from cs_analyzer.render.hud import ReplayHUD
from cs_analyzer.render.replay_animation import ReplayAnimationRenderer
from cs_analyzer.replay.timeline import Utility, build_timeline

from .conftest import S_ALICE, S_BOB, build_parsed_demo


def _demo_with_round_ticks():
    ticks = pd.DataFrame(
        {
            "tick": [0, 640, 1280, 1920, 2560, 2560, 3200, 3840, 4480, 5120],
            "steamid": [S_ALICE] * 10,
            "X": [0.0, 100.0, 200.0, 300.0, 400.0, 400.0, 500.0, 600.0, 700.0, 800.0],
            "Y": [0.0, 10.0, 20.0, 30.0, 40.0, 40.0, 50.0, 60.0, 70.0, 80.0],
            "is_alive": [True] * 10,
            "team_num": [3.0] * 10,
        }
    )
    return build_parsed_demo(ticks=ticks)


def _timeline(demo=None):
    return build_timeline(demo or _demo_with_round_ticks(), S_ALICE)


def test_shot_marker_zorder_below_trail() -> None:
    """Regression: shot flashes must not occlude the trail (below trail zorder 4)."""
    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    mgr = EffectManager(ReplayConfig(), tl, map_res, tick_rate=64)
    fig, ax = plt.subplots()
    mgr.attach(ax)
    assert mgr.shot_marks and mgr.shot_marks[0].get_zorder() == 3
    plt.close(fig)


def test_hud_feed_includes_utility_throws() -> None:
    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    tl.utilities["smoke"] = [Utility(tick=1000, x=100.0, y=10.0, kind="smoke")]
    hud = ReplayHUD(ReplayConfig(), tl, demo)
    assert any("投掷" in t[1] for t in hud.feed)


def test_hud_side_badge_color_feedback() -> None:
    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    cfg = ReplayConfig()
    hud = ReplayHUD(cfg, tl, demo)
    fig, ax = plt.subplots()
    hud.attach(fig, ax)
    hud.update(100.0, 1, "T", "test")
    assert hud._side_badge.get_text().startswith("阵营")
    assert hud._side_badge.get_color() == cfg.t_color
    hud.update(100.0, 1, "CT", "test")
    assert hud._side_badge.get_color() == cfg.ct_color
    plt.close(fig)


def test_opening_window_uses_config_seconds() -> None:
    """STG-1: openings window length follows config.opening_seconds (30s default)."""
    demo = _demo_with_round_ticks()
    r = ReplayAnimationRenderer(ReplayConfig(), demo)
    tl = _timeline(demo)
    wins = r._opening_windows(tl, opening=None, tick_rate=64)
    by_round = {n: (s, e) for n, s, e in wins}
    assert by_round[1][1] - by_round[1][0] == 1920  # 30s * 64 tick


# ---------- V1-V7 (Phase A polish) ----------


def test_alpha_scale_applies_to_effects() -> None:
    """V1: set_alpha_scale must scale every effect artist's alpha."""
    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    tl.utilities["smoke"] = [Utility(tick=1000, x=150.0, y=15.0, kind="smoke")]
    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    mgr = EffectManager(ReplayConfig(), tl, map_res, tick_rate=64)
    fig, ax = plt.subplots()
    mgr.attach(ax)
    tick = 1032.0  # half-way through the 1.0s smoke grow -> non-zero alpha
    mgr.set_alpha_scale(1.0)
    mgr.update(tick)
    full = [c.get_alpha() for c in mgr.smoke_circles]
    assert max(full) > 0
    mgr.set_alpha_scale(0.5)
    mgr.update(tick)
    half = [c.get_alpha() for c in mgr.smoke_circles]
    assert max(half) < max(full)
    assert max(half) == pytest.approx(max(full) * 0.5, rel=0.05)
    mgr.set_alpha_scale(0.0)
    mgr.update(tick)
    assert all(c.get_alpha() == 0 for c in mgr.smoke_circles)
    plt.close(fig)


def test_jump_marks_removed_triangle_only_ring() -> None:
    """V4: jump triangle pool is gone; only the expanding ring remains."""
    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    mgr = EffectManager(ReplayConfig(), tl, map_res, tick_rate=64)
    fig, ax = plt.subplots()
    mgr.attach(ax)
    assert not hasattr(mgr, "jump_marks")
    assert len(mgr.jump_rings) == 6
    plt.close(fig)


def test_smoke_multilayer_and_fire_flame_pools() -> None:
    """V7: smoke is a multi-layer cloud; fire is a flickering flame cluster."""
    demo = _demo_with_round_ticks()
    tl = _timeline(demo)
    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    mgr = EffectManager(ReplayConfig(), tl, map_res, tick_rate=64)
    fig, ax = plt.subplots()
    mgr.attach(ax)
    assert len(mgr.smoke_circles) == 8 * 5
    assert len(mgr.fire_flame_marks) == 8 * 8
    plt.close(fig)


def test_round_end_and_deadline_config_defaults() -> None:
    """V3/V6: round-end hold + winner banner + dead-line gray defaults."""
    cfg = ReplayConfig()
    assert cfg.round_end_hold_seconds == 1.2
    assert cfg.show_winner_banner is True
    assert cfg.dead_line_color == "#7A7A7A"


def test_team_palette_hue_spread() -> None:
    """V5: within-family palettes differ by hue, keeping T warm / CT cool."""
    from matplotlib.colors import rgb_to_hsv, to_rgb

    cfg = ReplayConfig()
    assert len(set(cfg.t_palette)) == len(cfg.t_palette)
    assert len(set(cfg.ct_palette)) == len(cfg.ct_palette)
    t_hue = [rgb_to_hsv(to_rgb(c))[0] for c in cfg.t_palette]
    ct_hue = [rgb_to_hsv(to_rgb(c))[0] for c in cfg.ct_palette]
    assert max(t_hue) < 0.2  # warm (yellow -> red)
    assert min(ct_hue) > 0.4  # cool (cyan -> blue)
    assert min(ct_hue) > max(t_hue)


class _FakeWriter:
    def __init__(self):
        self.grabbed = 0

    def grab_frame(self) -> None:
        self.grabbed += 1


def _team_demo_with_death():
    """One tracked player (Alice) who dies at tick 2000 in round 1 [0, 2560]."""
    ticks = pd.DataFrame(
        {
            "tick": list(range(0, 2561, 64)),
            "steamid": [S_ALICE] * 41,
            "X": [float(i) for i in range(41)],
            "Y": [0.0] * 41,
            "is_alive": [True] * 41,
            "team_num": [3.0] * 41,
        }
    )
    events = {
        "player_death": pd.DataFrame(
            {"tick": [2000], "user_steamid": [S_ALICE], "attacker_steamid": [S_BOB]}
        ),
        "round_freeze_end": pd.DataFrame({"tick": [500]}),
    }
    return build_parsed_demo(events=events, ticks=ticks)


def test_overlay_dead_line_turns_gray() -> None:
    """V6: in the 10-player overlay, a dead player's path turns gray."""
    from cs_analyzer.render.team_animation import TeamReplayRenderer

    demo = _team_demo_with_death()
    cfg = ReplayConfig()
    r = TeamReplayRenderer(cfg, demo)
    assert len(r.timelines) == 1
    fig, ax, lines, markers, corpse_marks, rlabel, hud_ctx, banner = r._setup_overlay_axes()
    rnd = demo.regular_rounds[0]
    fe = r.freeze.get(rnd.number, rnd.start_tick)
    windows = r._round_player_windows(rnd, fe)
    assert windows[0][2] == 2000  # alive window ends at death tick
    # alive portion -> original team color + position dot shown
    r._overlay_frame(lines, markers, corpse_marks, windows, 1000.0)
    assert lines[0].get_color() == r.colors[0]
    assert markers[0].get_alpha() > 0
    # after death -> gray line + corpse instead of the dot
    r._overlay_frame(lines, markers, corpse_marks, windows, 2300.0)
    assert lines[0].get_color() == cfg.dead_line_color
    assert markers[0].get_alpha() == 0
    assert corpse_marks[0].get_alpha() > 0
    # reset to original when the window still has the player alive
    r._overlay_frame(lines, markers, corpse_marks, windows, 800.0)
    assert lines[0].get_color() == r.colors[0]
    plt.close(fig)


def test_overlay_fade_hold_shows_winner_banner() -> None:
    """V3: round-end hold shows 'T/CT 获胜' banner and fades effects with paths."""
    from cs_analyzer.render.team_animation import _TeamView, TeamReplayRenderer

    demo = _team_demo_with_death()
    cfg = ReplayConfig()
    r = TeamReplayRenderer(cfg, demo)
    fig, ax, lines, markers, corpse_marks, rlabel, hud_ctx, banner = r._setup_overlay_axes()
    effects = EffectManager(cfg, _TeamView({}, []), r.map, tick_rate=64)
    effects.attach(ax)
    fake = _FakeWriter()
    hold = 12
    r._fade_hold(fake, lines, markers, corpse_marks, effects, 2500.0, hold, "T", banner)
    assert fake.grabbed == hold
    assert banner.get_text() == "T 获胜"
    assert banner.get_color() == cfg.t_color  # T winner -> warm banner
    assert not banner.get_visible()  # hidden after the hold
    assert effects._alpha_scale == 1.0  # reset for the next round
    plt.close(fig)


def test_continuous_hold_and_fade_shows_banner() -> None:
    """V2/V3: continuous renderer pauses per round with banner + fades trail/effects."""
    demo = _team_demo_with_death()
    cfg = ReplayConfig()
    from cs_analyzer.render.replay_animation import ReplayAnimationRenderer

    r = ReplayAnimationRenderer(cfg, demo)
    tl = build_timeline(demo, S_ALICE)
    fig, ax, ctx = r._setup_figure(tl)
    fake = _FakeWriter()
    ctx["trail_collection"].set_alpha(0.9)
    r._hold_and_fade(fake, ctx, 2500.0, 12, "CT")
    assert fake.grabbed == 12
    assert ctx["winner_banner"].get_text() == "CT 获胜"
    assert ctx["winner_banner"].get_color() == cfg.ct_color
    assert not ctx["winner_banner"].get_visible()
    assert ctx["effects"]._alpha_scale == 1.0
    plt.close(fig)
