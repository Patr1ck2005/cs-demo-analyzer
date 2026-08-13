"""Phase A (V1-V7) verification renders on a few rounds at low resolution.

Renders:
  * team overlay (t-overlap-round)  -> round-end winner banner + dead-line gray
  * team continuous (t-full)        -> per-round hold + winner banner + fade
  * single openings (s-openings)    -> overlay fade now scales effects too
  * a fire-heavy round (t-full)     -> molotov flame cluster / smoke cloud

Frame analysis (ffmpeg extraction) is done by the caller / verify script.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from cs_analyzer.cache import DemoCache
from cs_analyzer.config import ReplayConfig, load_settings
from cs_analyzer.parser.manager import ParseManager
from cs_analyzer.recipe import apply_style
from cs_analyzer.render.team_animation import TeamReplayRenderer
from cs_analyzer.render.replay_animation import ReplayAnimationRenderer

DEMO = Path("demos/9206943388297116556_0.dem")
OUT = Path("output/.verify_phase_a")
STAR = "⚡女帝⚡"


def low_res() -> ReplayConfig:
    settings = load_settings(None)
    with open("scripts/verify_polish.yaml", encoding="utf-8") as f:
        style = yaml.safe_load(f) or {}
    return apply_style(settings.render.replay, style)


def fire_round(renderer: TeamReplayRenderer) -> int | None:
    """Round with the most fire (molotov) events."""
    from collections import Counter

    counts = Counter()
    for ev in renderer.team_utils.get("fire", []):
        rnd = renderer.demo.data.round_at_tick(ev.tick)
        if rnd is not None:
            counts[rnd.number] += 1
    return counts.most_common(1)[0][0] if counts else None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    settings = load_settings(None)
    manager = ParseManager(cache=DemoCache(settings.cache_dir))
    demo = manager.parse(DEMO)

    cfg = low_res()
    renderer = TeamReplayRenderer(cfg, demo)

    # V3/V6: team per-round overlay with winner banner + dead-line gray
    renderer.render_overlay(OUT / "overlay_r1_2.mp4", per_round=True, speed=12.0)  # all rounds, low-res
    # V2/V3: continuous team render with round-end hold + banner
    renderer.render(OUT / "tfull_r1_2.mp4", rounds=[1, 2], speed=10.0)

    # V7: fire-heavy round continuous
    fr = fire_round(renderer)
    if fr:
        renderer.render(OUT / f"fire_r{fr}.mp4", rounds=[fr], speed=10.0)
        print(f"V7 fire round: {fr}")
    else:
        print("no fire events found in demo")

    # V1: single openings fade now scales effects
    single = ReplayAnimationRenderer(cfg, demo)
    single.render_player(STAR, OUT / "openings.mp4", mode="openings", speed=5.0, tick_rate=64)

    print("done ->", OUT)


if __name__ == "__main__":
    main()
