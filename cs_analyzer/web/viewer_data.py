"""Viewer-data artifact for the real-time canvas replay (Phase C, M2).

One precomputed JSON per demo: roster, tick-domain segments, downsampled
per-player state snapshots (position/yaw/hp/armor/alive/side/weapon), events
with world coordinates, and map metadata. The browser interpolates between
snapshots — zero pre-render wait, instant drag-seek at any speed.

Artifact: output/web/{hash}/viewer/viewer_data.json (version-gated like
replay_map.RENDER_VERSION; stale files are treated as missing).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.replay.timeline import round_freeze_ends

logger = logging.getLogger(__name__)

TICK_RATE = 64
SNAPSHOT_STRIDE = 8  # ticks between snapshots (8 Hz; 64/8 exact)
ROUND_CLOCK_SECONDS = 115.0
VIEWER_DATA_VERSION = 1

# demoparser2 0.41 exposes no clip/reserve props (probed across all demos,
# scripts/probe_ammo.py) — ammo ships as null until a parse route exists.
AMMO_AVAILABLE = False


def viewer_data_path(demo_hash: str, out_dir: Path) -> Path:
    return out_dir / demo_hash / "viewer" / "viewer_data.json"


def load_viewer_data(demo_hash: str, out_dir: Path) -> dict | None:
    p = viewer_data_path(demo_hash, out_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("viewer_version") != VIEWER_DATA_VERSION:
        return None
    return data


def is_ready(demo_hash: str, out_dir: Path) -> bool:
    return load_viewer_data(demo_hash, out_dir) is not None


def _short_weapon(name) -> str:
    n = str(name or "").strip()
    if n.startswith("weapon_"):
        n = n[len("weapon_"):]
    return n


def build_viewer_data(demo: ParsedDemo) -> dict:
    """Pure pandas/numpy walk over the cached demo (vectorized, target <10s)."""
    import numpy as np

    from cs_analyzer.maps.loader import load_map_or_fallback
    from cs_analyzer.web.replay_map import build_viewer_events

    ticks = demo.ticks
    freeze = round_freeze_ends(demo)

    # ---- segments (tick domain; client maps position <-> tick through them) ----
    segments = []
    for r in demo.regular_rounds:
        start = freeze.get(r.number, r.start_tick)
        end = r.end_tick
        if end <= start:
            continue
        segments.append(
            {
                "round": r.number,
                "start_tick": int(start),
                "end_tick": int(end),
                "t_score": r.t_score,
                "ct_score": r.ct_score,
                "winner_side": r.winner_side,
            }
        )

    # ---- global snapshot grid over all rounds ----
    grid_parts = []
    for seg in segments:
        grid_parts.append(np.arange(seg["start_tick"], seg["end_tick"], SNAPSHOT_STRIDE))
    grid_arr = np.unique(np.concatenate(grid_parts)) if grid_parts else np.array([], dtype=np.int64)
    n_grid = len(grid_arr)

    roster: list[dict] = []
    players: list[dict] = []
    if ticks is not None and not ticks.empty and {"steamid", "X", "Y"} <= set(ticks.columns):
        for p in demo.players:
            sub = ticks[ticks["steamid"] == p.steamid].sort_values("tick")
            if sub.empty or not sub["X"].notna().any():
                continue  # Team 0 / untracked player

            t = sub["tick"].to_numpy(dtype=np.int64)
            # side='right': a grid tick with no exact row snaps BACK to the last
            # known row of the same round (side='left' would leak the next
            # round's state into this round's tail snapshots).
            pos = np.searchsorted(t, grid_arr, side="right") - 1
            valid = pos >= 0
            vp = pos[valid]

            xs = sub["X"].to_numpy(dtype=float)[vp]
            ys = sub["Y"].to_numpy(dtype=float)[vp]
            finite = np.isfinite(xs) & np.isfinite(ys)

            def col(name: str, default=0.0) -> np.ndarray:
                if name in sub.columns:
                    v = sub[name].to_numpy(dtype=float)[vp]
                    return np.where(np.isfinite(v), v, default)
                return np.full(len(vp), default)

            yaw_v = col("yaw")
            hp_v = col("health").clip(0, 100).astype(np.int32)
            armor_v = col("armor").clip(0, 100).astype(np.int32)
            side_raw = col("team_num", default=3.0)
            alive_v = finite.copy()
            if "is_alive" in sub.columns:
                alive_v &= sub["is_alive"].astype(bool).to_numpy()[vp]

            # dead players keep their last known position (forward fill NaNs)
            px = np.where(finite, xs, np.nan)
            py = np.where(finite, ys, np.nan)
            px = pd_forward_fill(px)
            py = pd_forward_fill(py)
            px = np.nan_to_num(px, nan=0.0)
            py = np.nan_to_num(py, nan=0.0)

            weapon_names = (
                sub["active_weapon_name"].map(_short_weapon).to_numpy()
                if "active_weapon_name" in sub.columns
                else np.full(len(sub), "", dtype=object)
            )
            wv = weapon_names[vp]

            gticks = grid_arr[valid]
            roster.append({"steamid": p.steamid, "name": p.name})
            players.append(
                {
                    "steamid": p.steamid,
                    "t": gticks.astype(np.int64).tolist(),
                    "x": np.round(px, 1).tolist(),
                    "y": np.round(py, 1).tolist(),
                    "yaw": (np.round(yaw_v / 5.0) * 5.0).astype(float).tolist(),
                    "hp": hp_v.tolist(),
                    "armor": armor_v.tolist(),
                    "alive": alive_v.tolist(),
                    "side": [
                        ("T" if s == 2 else "CT") if s in (2.0, 3.0) else ""
                        for s in side_raw.tolist()
                    ],
                    "w": wv.tolist(),
                }
            )

    events = build_viewer_events(demo)
    map_res = load_map_or_fallback(demo.metadata.map_name, ticks)
    b = map_res.bounds

    return {
        "viewer_version": VIEWER_DATA_VERSION,
        "tick_rate": TICK_RATE,
        "stride": SNAPSHOT_STRIDE,
        "round_clock_seconds": ROUND_CLOCK_SECONDS,
        "ammo": AMMO_AVAILABLE,
        "demo_hash": demo.metadata.demo_hash,
        "map_name": demo.metadata.map_name,
        "map": {
            "image_url": f"/maps/{demo.metadata.map_name}.png",
            "width": map_res.image_width,
            "height": map_res.image_height,
            "bounds": {
                "min_x": b.min_x, "max_x": b.max_x,
                "min_y": b.min_y, "max_y": b.max_y,
            },
        },
        "segments": segments,
        "roster": roster,
        "players": players,
        "events": events,
    }


def pd_forward_fill(arr):
    """Forward-fill NaNs in a 1-D array (dead rows keep last position).

    Leading NaNs (no finite predecessor) stay NaN.
    """
    import numpy as np

    mask = np.isnan(arr)
    if not mask.any():
        return arr
    idx = np.where(~mask, np.arange(len(arr)), 0)
    np.maximum.accumulate(idx, out=idx)
    return arr[idx]


def build_and_save(demo: ParsedDemo, out_dir: Path) -> tuple[Path, int]:
    """Build the payload, write it, return (path, raw byte size)."""
    payload = build_viewer_data(demo)
    path = viewer_data_path(demo.metadata.demo_hash, out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    size = len(text.encode("utf-8"))
    logger.info("viewer-data %s: %.2f MB raw", demo.metadata.demo_hash[:12], size / 1e6)
    return path, size
