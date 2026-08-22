"""Declarative render recipes: named, fine-grained-customizable video recipes.

A recipe declares a target (single player / team), a renderer mode, playback
speed/selection, and a `style` block. The style block is nested for readability
but flattened onto ReplayConfig fields before rendering, so ANY fine-grained
knob (effect toggles/colors, trail, HUD, palettes, canvas) can be overridden.

Usage:
    recipes = load_recipes(Path("configs/recipes.yaml"))
    result = render_recipe(demo, recipes["s-openings"], out, player=steamid)
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from cs_analyzer.config import ReplayConfig
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

# Nested style sections -> flat ReplayConfig field overrides.
_STYLE_MAP: dict[str, dict[str, str]] = {
    "canvas": {"width": "width", "height": "height", "dpi": "dpi", "fps": "fps", "bg": "bg_color"},
    "trail": {"enabled": "trail_enabled", "seconds": "trail_seconds",
              "width_min": "trail_width_min", "width_max": "trail_width_max",
              "alpha_min": "trail_alpha_min", "alpha_max": "trail_alpha_max",
              "break_distance": "break_distance"},
    "marker": {"size": "player_marker_size", "edge": "player_marker_edge",
               "halo": "halo_enabled", "halo_size": "halo_size"},
    "hud": {"show_score": "hud_show_score", "show_round": "hud_show_round",
            "show_clock": "hud_show_clock", "show_feed": "hud_show_feed",
            "show_legend": "hud_show_legend"},
    "team": {"t_palette": "t_palette", "ct_palette": "ct_palette",
             "t_color": "t_color", "ct_color": "ct_color"},
    "round_end": {"hold_seconds": "round_end_hold_seconds",
                  "fade_seconds": "overlay_fade_seconds",
                  "show_banner": "show_winner_banner"},
}


def flatten_style(style: dict) -> dict:
    """Convert a nested recipe style into flat ReplayConfig field overrides.

    - Sections in _STYLE_MAP map nested keys to flat fields (canvas/trail/...).
    - `effects.*` sub-keys are already flat ReplayConfig field names and are
      promoted to the top level.
    - Anything else (font, nade_flight_seconds, ...) passes through as-is.
    """
    flat: dict = {}
    for key, val in (style or {}).items():
        if key in _STYLE_MAP:
            for sub, target in _STYLE_MAP[key].items():
                if isinstance(val, dict) and sub in val:
                    flat[target] = val[sub]
        elif key == "effects":
            flat.update(val or {})
        else:
            flat[key] = val
    return flat


def apply_style(config: ReplayConfig, style: dict) -> ReplayConfig:
    """Return a copy of `config` with the flattened style overrides applied."""
    flat = flatten_style(style)
    fields = type(config).model_fields
    unknown = [k for k in flat if k not in fields]
    if unknown:
        logger.warning("recipe style ignored unknown keys: %s", unknown)
    known = {k: v for k, v in flat.items() if k in fields}
    if not known:
        return config
    return config.model_copy(update=known)


class Recipe:
    """A declarative render recipe."""

    def __init__(self, name: str, data: dict) -> None:
        self.name = name
        self.title = data.get("title", name)
        self.kind = data.get("kind", "single")  # single | team
        self.mode = data.get("mode", "overlap-full")
        self.speed = data.get("speed")
        self.rounds = data.get("rounds")
        self.opening = data.get("opening")
        self.highlight = data.get("highlight")
        self.style = data.get("style", {}) or {}

    def as_dict(self) -> dict:
        return {
            "title": self.title, "kind": self.kind, "mode": self.mode,
            "speed": self.speed, "rounds": self.rounds, "opening": self.opening,
            "highlight": self.highlight, "style": self.style,
        }


def load_recipes(path: Path | str) -> dict[str, Recipe]:
    """Load recipes from a YAML file."""
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {name: Recipe(name, d) for name, d in data.items()}


def render_recipe(
    demo: ParsedDemo,
    recipe: Recipe,
    output_path: Path | str,
    player: str | None = None,
    overrides: dict | None = None,
    base_config: ReplayConfig | None = None,
) -> Path:
    """Render a recipe on a parsed demo.

    `overrides` is a (possibly nested) style dict from a --config override YAML,
    merged on top of the recipe's own style.
    """
    cfg = apply_style(base_config or ReplayConfig(), recipe.style)
    cfg = apply_style(cfg, overrides or {})
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if recipe.kind == "team":
        from cs_analyzer.render.team_animation import TeamReplayRenderer

        renderer = TeamReplayRenderer(cfg, demo)
        rounds = recipe.rounds
        if recipe.mode in ("team-highlights", "team-highlight") and rounds is None:
            rounds = _team_highlight_rounds(renderer)
        if recipe.mode == "team-highlight":
            hl = recipe.highlight or player
            if not hl:
                raise ValueError("team-highlight recipe needs a --player / highlight steamid")
            return renderer.render(output_path, rounds=rounds, speed=recipe.speed, highlight_steamid=hl)
        if recipe.mode == "team-overlap-round":
            return renderer.render_overlay(output_path, per_round=True, speed=recipe.speed)
        if recipe.mode == "team-overlap-full":
            return renderer.render_overlay(output_path, per_round=False, speed=recipe.speed)
        return renderer.render(output_path, rounds=rounds, speed=recipe.speed)

    # single player
    if not player:
        raise ValueError(f"recipe '{recipe.name}' (single) needs a --player steamid/name")
    from cs_analyzer.render.replay_animation import ReplayAnimationRenderer

    renderer = ReplayAnimationRenderer(cfg, demo)
    return renderer.render_player(
        player, output_path, mode=recipe.mode, speed=recipe.speed,
        rounds=recipe.rounds, opening=recipe.opening,
    )


def _team_highlight_rounds(renderer, k: int = 3) -> list[int]:
    counts: dict[int, int] = {}
    for tl in renderer.timelines:
        for kk in tl.kills:
            rnd = renderer.demo.data.round_at_tick(kk.tick)
            if rnd is not None:
                counts[rnd.number] = counts.get(rnd.number, 0) + 1
    return [n for n, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:k]]
