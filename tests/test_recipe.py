"""Tests for the declarative render recipe system."""
from __future__ import annotations

import pandas as pd
import pytest

from cs_analyzer.config import ReplayConfig
from cs_analyzer.recipe import apply_style, flatten_style, load_recipes, render_recipe

from .conftest import S_ALICE, build_parsed_demo
from .test_replay import _demo_with_round_ticks

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


def _recipes():
    return load_recipes(REPO / "configs/recipes.yaml")


def test_load_recipes_has_all_seven() -> None:
    recipes = _recipes()
    assert set(recipes) >= {
        "s-overlap-full", "s-openings", "s-highlights",
        "t-full", "t-highlights", "t-highlight", "t-overlap-round", "t-overlap-full",
    }


def test_flatten_style_maps_nested_sections() -> None:
    style = {
        "canvas": {"width": 800, "height": 450, "bg": "#000000"},
        "trail": {"seconds": 2.0, "width_min": 2.0},
        "hud": {"show_feed": False},
        "marker": {"halo": False},
        "team": {"t_palette": ["#111111"]},
        "effects": {"show_smoke": False, "smoke_max_radius": 200.0},
    }
    flat = flatten_style(style)
    assert flat["width"] == 800
    assert flat["bg_color"] == "#000000"
    assert flat["trail_seconds"] == 2.0
    assert flat["hud_show_feed"] is False
    assert flat["halo_enabled"] is False
    assert flat["t_palette"] == ["#111111"]
    assert flat["show_smoke"] is False
    assert flat["smoke_max_radius"] == 200.0


def test_apply_style_overrides_fields() -> None:
    cfg = apply_style(ReplayConfig(), {"canvas": {"fps": 12}, "effects": {"show_smoke": False}})
    assert cfg.fps == 12
    assert cfg.show_smoke is False
    assert cfg.width == 1280  # untouched


def test_apply_style_ignores_unknown_keys() -> None:
    cfg = apply_style(ReplayConfig(), {"nope": 1, "effects": {"smoke_max_radius": 90.0}})
    assert cfg.smoke_max_radius == 90.0  # known key applied
    assert not hasattr(cfg, "nope")  # unknown ignored


@pytest.mark.skipif(
    __import__("cs_analyzer.utils.ffmpeg", fromlist=["find_ffmpeg"]).find_ffmpeg() is None,
    reason="ffmpeg not available",
)
def test_render_recipe_single_smoke(tmp_path) -> None:
    recipes = _recipes()
    demo = _demo_with_round_ticks()
    # use s-highlights with a round override to keep it tiny
    rec = recipes["s-highlights"]
    rec.speed = 60.0
    rec.rounds = [1]
    out = render_recipe(demo, rec, tmp_path / "r.mp4", player=S_ALICE)
    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(
    __import__("cs_analyzer.utils.ffmpeg", fromlist=["find_ffmpeg"]).find_ffmpeg() is None,
    reason="ffmpeg not available",
)
def test_render_recipe_team_smoke(tmp_path) -> None:
    from cs_analyzer.render.team_animation import TeamReplayRenderer
    from .test_team import _team_demo

    recipes = _recipes()
    rec = recipes["t-overlap-round"]
    rec.speed = 80.0
    demo = _team_demo()
    out = render_recipe(demo, rec, tmp_path / "r_team.mp4")
    assert out.exists()
    assert out.stat().st_size > 0
