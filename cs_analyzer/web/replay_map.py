"""2D map replay viewer backend (Phase B2, MVP = pre-rendered video + drag seek).

Pre-renders a whole-match team replay with TeamReplayRenderer and records a
deterministic segment map (per-round tick ranges + video frame ranges + round-
end holds) plus timeline events (round winners, kills, utility throws) into
`map.json` next to the video. The frontend maps video time <-> game tick
through these segments for the draggable timeline / event markers.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from cs_analyzer.config import ReplayConfig
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.replay.timeline import round_freeze_ends

logger = logging.getLogger(__name__)

TICK_RATE = 64
VIEWER_SPEED_DEFAULT = 10.0

# Bump when rendered-output semantics change (e.g. basemap added, renderer
# upgrade) so cached viewer artifacts are treated as stale and re-rendered.
RENDER_VERSION = 2

# detonate event name -> Chinese label for the timeline legend
_UTILITY_KINDS = {
    "smokegrenade_detonate": "烟雾",
    "flashbang_detonate": "闪光",
    "hegrenade_detonate": "HE",
    "molotov_detonate": "燃烧瓶",
    "incendiary_detonate": "燃烧瓶",
}


def _finite(v) -> float:
    """Coerce to a finite float (Team 0 players carry all-NaN positions)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def _text(v) -> str:
    """Coerce event name fields to a string (raw tables hold NaN for absent
    names, e.g. suicide / Team 0 attacker)."""
    if v is None:
        return ""
    if isinstance(v, float) and not math.isfinite(v):
        return ""
    return str(v)


def viewer_config(base: ReplayConfig | None = None) -> ReplayConfig:
    """Dedicated config for the whole-match viewer render (kept modest so the
    pre-render finishes quickly while still being seekable)."""
    cfg = base or ReplayConfig()
    return cfg.model_copy(
        update={
            "width": 640,
            "height": 360,
            "fps": 20,
            "dpi": 100,
            "speed_team": VIEWER_SPEED_DEFAULT,
            "max_frames": 30000,
            "trail_seconds": 1.0,
        }
    )


def build_viewer_segments(
    demo: ParsedDemo, config: ReplayConfig, speed: float, tick_rate: int = TICK_RATE
) -> list[dict]:
    """Per-round segment structure: tick range, video frame range, round-end
    hold frames and winner. Frame math mirrors TeamReplayRenderer.render()."""
    freeze = round_freeze_ends(demo)
    fps = config.fps
    hold = int(fps * config.round_end_hold_seconds) if config.round_end_hold_seconds > 0 else 0
    video_frame = 0
    segs = []
    for r in demo.regular_rounds:
        start = freeze.get(r.number, r.start_tick)
        end = r.end_tick
        if end <= start:
            continue
        n = max(int((end - start) / (tick_rate * speed / fps)), 1)
        segs.append(
            {
                "round": r.number,
                "start_tick": start,
                "end_tick": end,
                "n_frames": n,
                "hold_frames": hold,
                "video_start": video_frame,
                "video_end": video_frame + n + hold,
                "winner_side": r.winner_side,
            }
        )
        video_frame += n + hold
    return segs


def build_viewer_events(demo: ParsedDemo) -> dict:
    """Timeline events from the raw event tables (cheap, covers all players)."""
    rounds = [
        {
            "number": r.number,
            "winner_side": r.winner_side,
            "start_tick": r.start_tick,
            "end_tick": r.end_tick,
        }
        for r in demo.regular_rounds
    ]
    kills = []
    df = demo.events.get("player_death")
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            kills.append(
                {
                    "tick": int(row.get("tick", 0) or 0),
                    "attacker": _text(row.get("attacker_name", "")),
                    "victim": _text(row.get("user_name", "")),
                    "weapon": _text(row.get("weapon", "")),
                }
            )
        kills.sort(key=lambda k: k["tick"])
    utils = []
    for ev_name, label in _UTILITY_KINDS.items():
        df = demo.events.get(ev_name)
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            utils.append(
                {
                    "tick": int(row.get("tick", 0) or 0),
                    "kind": label,
                    "x": _finite(row.get("x", 0)),
                    "y": _finite(row.get("y", 0)),
                }
            )
    utils.sort(key=lambda u: u["tick"])
    return {"rounds": rounds, "kills": kills, "utilities": utils}


def map_path(demo_hash: str, out_dir: Path) -> Path:
    return out_dir / demo_hash / "viewer" / "map.json"


def video_path(demo_hash: str, out_dir: Path) -> Path:
    return out_dir / demo_hash / "viewer" / "replay.mp4"


def load_map(demo_hash: str, out_dir: Path) -> dict | None:
    p = map_path(demo_hash, out_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # stale renders (pre-basemap etc.) must not be served as ready
    if data.get("render_version") != RENDER_VERSION:
        return None
    return data


def is_ready(demo_hash: str, out_dir: Path) -> bool:
    return video_path(demo_hash, out_dir).exists() and load_map(demo_hash, out_dir) is not None


def render_viewer_job(
    demo_hash: str, demo: ParsedDemo, out_dir: Path, speed: float
) -> str:
    """Pre-render the whole-match team replay + write map.json (background job)."""
    from cs_analyzer.render.team_animation import TeamReplayRenderer

    cfg = viewer_config()
    out_dir = out_dir / demo_hash / "viewer"
    out_dir.mkdir(parents=True, exist_ok=True)
    video = out_dir / "replay.mp4"
    renderer = TeamReplayRenderer(cfg, demo)
    logger.info("viewer pre-render: %s speed=%s", demo_hash, speed)
    renderer.render(video, speed=speed)
    segs = build_viewer_segments(demo, cfg, speed)
    events = build_viewer_events(demo)
    payload = {
        "render_version": RENDER_VERSION,
        "fps": cfg.fps,
        "speed": speed,
        "tick_rate": TICK_RATE,
        "video": "replay.mp4",
        "segments": segs,
        "events": events,
        "total_frames": segs[-1]["video_end"] if segs else 0,
    }
    map_path_ = out_dir / "map.json"
    map_path_.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    return str(video)
