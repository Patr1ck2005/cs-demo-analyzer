"""Export a curated acceptance set of replay videos for review.

Renders at 960x540@30 (review quality) with all effects + HUD on (defaults),
on a few rounds each to bound render time. Output -> output/acceptance/.

  1. acceptance_team_overlay.mp4    team per-round overlay (rounds 1-4): winner
                                     banner, dead-line gray, player markers
  2. acceptance_team_full.mp4       team continuous (rounds 1-4): round-end
                                     hold + banner + effects fade
  3. acceptance_team_highlights.mp4 team top-3 kill rounds
  4. acceptance_single_highlights   single-player highlights for the star
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cs_analyzer.cache import DemoCache
from cs_analyzer.config import ReplayConfig, load_settings
from cs_analyzer.parser.manager import ParseManager
from cs_analyzer.render.replay_animation import ReplayAnimationRenderer
from cs_analyzer.render.team_animation import TeamReplayRenderer
from cs_analyzer.replay.timeline import build_timeline

DEMO = Path("demos/9206943388297116556_0.dem")
STAR = "⚡女帝⚡"
OUT = Path("output/acceptance")


def review_cfg() -> ReplayConfig:
    s = load_settings(None)
    return s.render.replay.model_copy(
        update={"width": 960, "height": 540, "fps": 30, "dpi": 100, "max_frames": 30000}
    )


def top_kill_rounds(demo, timelines, k: int = 3) -> list[int]:
    counts: Counter[int] = Counter()
    for tl in timelines:
        for kk in tl.kills:
            rnd = demo.data.round_at_tick(kk.tick)
            if rnd is not None:
                counts[rnd.number] += 1
    return [n for n, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:k]]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = load_settings(None)
    demo = ParseManager(cache=DemoCache(s.cache_dir)).parse(DEMO)
    cfg = review_cfg()
    team = TeamReplayRenderer(cfg, demo)

    print("[1/4] team overlay (rounds 1-4) ...", flush=True)
    team.render_overlay(OUT / "acceptance_team_overlay.mp4", per_round=True, speed=6.0)

    print("[2/4] team full (rounds 1-4) ...", flush=True)
    team.render(OUT / "acceptance_team_full.mp4", rounds=[1, 2, 3, 4], speed=6.0)

    tr = top_kill_rounds(demo, team.timelines, 3)
    print(f"[3/4] team highlights (rounds {tr}) ...", flush=True)
    team.render(OUT / "acceptance_team_highlights.mp4", rounds=tr, speed=4.0)

    single = ReplayAnimationRenderer(cfg, demo)
    tl = build_timeline(demo, STAR)
    sr = top_kill_rounds(demo, [tl], 3)
    print(f"[4/4] single highlights {STAR} (rounds {sr}) ...", flush=True)
    single.render_player(STAR, OUT / "acceptance_single_highlights.mp4",
                         mode="highlights", speed=2.0, rounds=sr)

    print("DONE ->", OUT, flush=True)


if __name__ == "__main__":
    main()
