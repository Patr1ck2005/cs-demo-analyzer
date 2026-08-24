"""Viewer-data artifacts for the real-time canvas replay (Phase C/E).

Two JSON artifacts per demo under output/web/{hash}/viewer/:

- viewer_data.json (VIEWER_DATA_VERSION): base payload the canvas viewer
  fetches on load — roster, tick-domain segments, downsampled per-player
  state snapshots (position/yaw/hp/armor/alive/side/weapon-interned), events
  (kills with coordinates/headshot, utilities with reconstructed throws and
  real durations, blinds, bomb events), map metadata and real team names.
  The browser interpolates between snapshots — zero pre-render wait,
  instant drag-seek at any speed.

- viewer_layers.json (LAYER_VERSION): optional heavy layers served lazily
  through /api/demo/{h}/viewer-layers?with=shots,economy — per-shot firing
  points and per-round purchase summaries. Missing layers degrade gracefully
  client-side (the matching overlay toggles stay disabled).

Stale artifacts are treated as missing via the version gates below.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.replay.timeline import TICK_RATE, round_freeze_ends

logger = logging.getLogger(__name__)

TICK_RATE = 64
SNAPSHOT_STRIDE = 8  # ticks between snapshots (8 Hz; 64/8 exact)
ROUND_CLOCK_SECONDS = 115.0
VIEWER_DATA_VERSION = 3
LAYER_VERSION = 2  # v2: shots carry shooter yaw ("ya") for tracer rendering

# demoparser2 >= 0.42 exposes per-tick ammo (probed on all real demos,
# output/.ammo_probe.json). Detection is dynamic: older caches re-parse lazily
# via PARSER_VERSION, so the columns are simply expected to be there.
_AMMO_TICK_COLS = ("active_weapon_ammo", "is_in_reload")

# side enum used in snapshot arrays (was "T"/"CT"/"" strings in v1)
SIDE_T, SIDE_CT, SIDE_UNKNOWN = 0, 1, 2

# utility kinds emitted to the client (timeline "molly" collapses into
# "fire": molotov_detonate never materializes in SourceTV demos, inferno_* is
# the real signal)
_UTILITY_EMIT_KINDS = {"smoke": "smoke", "flash": "flash", "he": "he",
                       "molly": "fire", "fire": "fire"}

# default zone lifetimes (game seconds) when no real duration was matched;
# mirrors UTILITY_DEFAULT_SECONDS in replay/timeline.py
_UTILITY_DEFAULT_S = {"smoke": 18.0, "flash": 2.0, "he": 1.0, "fire": 7.0}

_BOMB_TABLES = (("bomb_planted", "plant"), ("bomb_defused", "defuse"),
                ("bomb_exploded", "explode"))

_GRENADE_ITEM_PREFIXES = ("smoke", "flash", "hegrenade", "molotov", "incendiary", "decoy")


def viewer_data_path(demo_hash: str, out_dir: Path) -> Path:
    return out_dir / demo_hash / "viewer" / "viewer_data.json"


def load_viewer_data(demo_hash: str, out_dir: Path) -> dict | None:
    return _load_versioned(viewer_data_path(demo_hash, out_dir), VIEWER_DATA_VERSION, "viewer_version")


def is_ready(demo_hash: str, out_dir: Path) -> bool:
    return load_viewer_data(demo_hash, out_dir) is not None


def viewer_layers_path(demo_hash: str, out_dir: Path) -> Path:
    return out_dir / demo_hash / "viewer" / "viewer_layers.json"


def load_viewer_layers(demo_hash: str, out_dir: Path) -> dict | None:
    return _load_versioned(viewer_layers_path(demo_hash, out_dir), LAYER_VERSION, "layer_version")


def _load_versioned(path: Path, version: int, key: str) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get(key) != version:
        return None
    return data


def _short_weapon(name) -> str:
    n = str(name or "").strip()
    if n.startswith("weapon_"):
        n = n[len("weapon_"):]
    return n


class _WeaponTable:
    """String interning: emit each weapon name once, snapshots carry indexes."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self._idx: dict[str, int] = {}

    def index(self, name: str) -> int:
        i = self._idx.get(name)
        if i is None:
            i = len(self.names)
            self._idx[name] = i
            self.names.append(name)
        return i


def _finite(v) -> float:
    """Coerce to a finite float (Team 0 players carry all-NaN positions)."""
    import math

    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def _finite_or_none(v):
    """Finite float or None (JSON null) — e.g. suicide/world deaths carry NaN
    coordinates and the client draws a skull without a kill line."""
    import math

    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _text(v) -> str:
    """Coerce event name fields to a string (raw tables hold NaN for absent
    names, e.g. suicide / Team 0 attacker)."""
    import math

    if v is None:
        return ""
    if isinstance(v, float) and not math.isfinite(v):
        return ""
    return str(v)


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


def _union_reload_flag(prop_flag, prop_ticks, event_ticks, event_pad=(0, 96)):
    """Merge the is_in_reload prop with weapon_reload event runs.

    event ticks fire per-tick during a reload; each run (gap<=2) padded by
    event_pad ticks marks one reload window. Returns a flag array aligned to
    prop_ticks (same length as prop_flag).
    """
    import numpy as np

    out = np.asarray(prop_flag, dtype=np.int8).copy()
    if len(event_ticks) == 0:
        return out
    et = np.sort(np.asarray(event_ticks, dtype=np.int64))
    # collapse consecutive event ticks into runs
    starts = [et[0]]
    prev = et[0]
    for x in et[1:]:
        if x > prev + 2:
            starts.append(x)
        prev = x
    tick_arr = np.asarray(prop_ticks, dtype=np.int64)
    lo, hi = event_pad
    for s in starts:
        mask = (tick_arr >= s + lo) & (tick_arr <= s + hi)
        out[mask] = 1
    return out


def _team_names(demo: ParsedDemo) -> dict[str, str]:
    """Real team names from begin_new_match ("" falls back to T/CT client-side)."""
    df = demo.events.get("begin_new_match")
    t = ct = ""
    if df is not None and not df.empty:
        row = df.iloc[-1]
        t = _text(row.get("t_team_name", ""))
        ct = _text(row.get("ct_team_name", ""))
    return {"t": t, "ct": ct}


def build_viewer_data(demo: ParsedDemo) -> dict:
    """Pure pandas/numpy walk over the cached demo (vectorized, target <10s)."""
    import numpy as np

    from cs_analyzer.maps.loader import load_map_or_fallback

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

    roster: list[dict] = []
    players: list[dict] = []
    weapons = _WeaponTable()
    has_ammo = ticks is not None and set(_AMMO_TICK_COLS) <= set(ticks.columns)
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

            weapon_shorts = (
                sub["active_weapon_name"].map(_short_weapon).to_numpy()
                if "active_weapon_name" in sub.columns
                else np.full(len(sub), "", dtype=object)
            )

            # v3: per-tick magazine + reload flag (grenades/knife carry 0)
            if has_ammo:
                ammo_v = col("active_weapon_ammo").clip(0, 999).astype(np.int32)
                reload_v = col("is_in_reload").astype(np.int8)
                # The is_in_reload prop misses some reloads on certain WMPVP
                # players (0762: 1 span vs 3 event runs); the weapon_reload
                # event fires per-tick DURING the reload, so its run starts
                # are the complementary signal. Union of both = robust window
                # (97% of prop spans confirmed by ammo refills, see dev_log).
                # NOTE: reload_v/ammo_v are indexed by vp (grid positions),
                # not by raw sub rows — union must map event windows through
                # the same vp index.
                ev_reload = demo.events.get("weapon_reload")
                if ev_reload is not None and not ev_reload.empty:
                    ev_ticks = ev_reload[ev_reload["user_steamid"].astype(str) == p.steamid][
                        "tick"
                    ].to_numpy(dtype=np.int64)
                    reload_v = _union_reload_flag(
                        reload_v, sub["tick"].to_numpy(dtype=np.int64)[vp], ev_ticks
                    )

            side_codes = [SIDE_T if s == 2.0 else SIDE_CT if s == 3.0 else SIDE_UNKNOWN
                          for s in side_raw.tolist()]
            gticks = grid_arr[valid]
            roster.append({
                "steamid": p.steamid,
                "name": p.name,
                "side_first": next(("T" if c == SIDE_T else "CT" for c in side_codes
                                    if c != SIDE_UNKNOWN), ""),
            })
            entry = {
                "steamid": p.steamid,
                "t": gticks.astype(np.int64).tolist(),
                "x": np.round(px, 1).tolist(),
                "y": np.round(py, 1).tolist(),
                "yaw": (np.round(yaw_v / 5.0) * 5.0).astype(np.int32).tolist(),
                "hp": hp_v.tolist(),
                "armor": armor_v.tolist(),
                "alive": alive_v.astype(np.int8).tolist(),
                "side": side_codes,
                "w": [weapons.index(str(w)) for w in weapon_shorts[vp]],
            }
            if has_ammo:
                entry["am"] = ammo_v.tolist()
                entry["rl"] = reload_v.tolist()
            players.append(entry)

    events = {
        **_kill_events(demo, weapons),
        **_utility_events(demo),
        "blinds": _blind_events(demo),
        "bombs": _bomb_events(demo, ticks),
    }
    map_res = load_map_or_fallback(demo.metadata.map_name, ticks)
    b = map_res.bounds

    return {
        "viewer_version": VIEWER_DATA_VERSION,
        "tick_rate": TICK_RATE,
        "stride": SNAPSHOT_STRIDE,
        "round_clock_seconds": ROUND_CLOCK_SECONDS,
        "ammo": has_ammo,
        "demo_hash": demo.metadata.demo_hash,
        "map_name": demo.metadata.map_name,
        "teams": _team_names(demo),
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
        "weapon_table": weapons.names,
        "players": players,
        "events": events,
    }


def _kill_events(demo: ParsedDemo, weapons: _WeaponTable) -> dict:
    """Kills with world coordinates (attacker_X/Y + user_X/Y), headshot flag
    and interned weapon index. Names stay in the payload so kills involving
    Team 0 players (absent from the roster) still render in the feed."""
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
                    "ax": _finite_or_none(row.get("attacker_X")),
                    "ay": _finite_or_none(row.get("attacker_Y")),
                    "vx": _finite_or_none(row.get("user_X")),
                    "vy": _finite_or_none(row.get("user_Y")),
                    "hs": 1 if int(row.get("headshot", 0) or 0) else 0,
                    "wi": weapons.index(_short_weapon(_text(row.get("weapon", "")))),
                    "att": _text(row.get("attacker_steamid", "")),
                    "vic": _text(row.get("user_steamid", "")),
                    "an": _text(row.get("attacker_name", "")),
                    "vn": _text(row.get("user_name", "")),
                }
            )
        kills.sort(key=lambda k: k["tick"])
    return {"rounds": rounds, "kills": kills}


def _utility_events(demo: ParsedDemo) -> dict:
    """Utilities with reconstructed throw origins and REAL lifetimes.

    Reuses replay/timeline.build_timeline per tracked player: this inherits
    the *_expired entityid duration matching and the flight-time throw
    reconstruction verbatim. Position-less players (Team 0) raise inside
    build_timeline and are skipped (their utility zones would have no owner
    trail anyway).
    """
    from cs_analyzer.replay.timeline import build_timeline

    out: list[dict] = []
    for p in demo.players:
        try:
            tl = build_timeline(demo, p.steamid)
        except ValueError:
            continue  # Team 0 / untracked player
        for kind, evs in tl.utilities.items():
            emit_kind = _UTILITY_EMIT_KINDS.get(kind, kind)
            for e in evs:
                throw_tick = e.throw_tick if e.throw_tick >= 0 else None
                out.append(
                    {
                        "tick": int(e.tick),
                        "kind": emit_kind,
                        "x": round(float(e.x), 1),
                        "y": round(float(e.y), 1),
                        "tt": throw_tick,
                        "tx": round(float(e.throw_x), 1) if throw_tick is not None else None,
                        "ty": round(float(e.throw_y), 1) if throw_tick is not None else None,
                        # 0 => client uses its per-kind default (unmatched entity)
                        "dur_s": round(e.duration_ticks / TICK_RATE, 1) if e.duration_ticks else 0.0,
                        "sid": p.steamid,
                    }
                )
    out.sort(key=lambda u: u["tick"])
    return {"utilities": out}


def _blind_events(demo: ParsedDemo) -> list[dict]:
    """Flash-assist pairs: who blinded whom and for how long (seconds)."""
    df = demo.events.get("player_blind")
    out: list[dict] = []
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        dur = _finite(row.get("blind_duration", 0))
        if dur <= 0:
            continue
        out.append(
            {
                "tick": int(row.get("tick", 0) or 0),
                "dur": round(dur, 1),
                "att": _text(row.get("attacker_steamid", "")),
                "vic": _text(row.get("user_steamid", "")),
            }
        )
    out.sort(key=lambda b: b["tick"])
    return out


def _bomb_events(demo: ParsedDemo, ticks) -> list[dict]:
    """Plant/defuse/explode markers with a three-tier coordinate fallback:
    event coordinates -> planter position interpolated from tick rows -> null
    (client renders a site-label chip instead of a map pin)."""
    out: list[dict] = []

    def planter_xy(sid: str, tick: int):
        if not sid or ticks is None or ticks.empty:
            return None, None
        sub = ticks[ticks["steamid"] == sid].sort_values("tick")
        if sub.empty or not sub["X"].notna().any():
            return None, None
        import numpy as np

        t = sub["tick"].to_numpy(dtype=float)
        x = float(np.interp(tick, t, sub["X"].to_numpy(dtype=float)))
        y = float(np.interp(tick, t, sub["Y"].to_numpy(dtype=float)))
        import math

        if not (math.isfinite(x) and math.isfinite(y)):
            return None, None
        return round(x, 1), round(y, 1)

    for table, type_code in _BOMB_TABLES:
        df = demo.events.get(table)
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            sid = _text(row.get("user_steamid", "") or row.get("steamid", ""))
            tick = int(row.get("tick", 0) or 0)
            x = _finite_or_none(row.get("user_X"))
            y = _finite_or_none(row.get("user_Y"))
            if x is None:
                x, y = planter_xy(sid, tick)
            out.append(
                {
                    "tick": tick,
                    "type": type_code,
                    "site": _text(row.get("site", "")) or None,
                    "x": x,
                    "y": y,
                    "sid": sid,
                }
            )
    out.sort(key=lambda b: b["tick"])
    return out


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


# ---- heavy layers artifact (lazy-loaded overlays) ----

LAYER_KEYS = ("shots", "economy")


def build_viewer_layers(demo: ParsedDemo, keys: tuple[str, ...] = LAYER_KEYS) -> dict:
    """Shots (per-bullet firing points) and per-round economy summaries.

    Kept out of the base payload: ~1600 shot rows and the purchase log would
    grow every initial page-load for overlays most sessions never open.
    The layers artifact ships its own weapon_table (self-contained).
    """
    weapons = _WeaponTable()
    payload: dict = {"layer_version": LAYER_VERSION}
    if "shots" in keys:
        payload["shots"] = _shot_events(demo, weapons)
    if "economy" in keys:
        payload["economy"] = _economy_events(demo, weapons)
    payload["weapon_table"] = weapons.names
    return payload


def _shot_events(demo: ParsedDemo, weapons: _WeaponTable) -> list[dict]:
    df = demo.events.get("weapon_fire")
    out: list[dict] = []
    if df is None or df.empty:
        return out
    # shooter yaw at the fire tick (v2 layers): np.interp against each player's
    # sorted tick/yaw arrays — one pass per shooter, no per-row scans
    ticks_df = demo.ticks
    yaw_by_sid: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    if ticks_df is not None and not ticks_df.empty and {"steamid", "tick", "yaw"} <= set(ticks_df.columns):
        for sid, sub in ticks_df.groupby("steamid"):
            sub = sub.sort_values("tick")
            yaw_by_sid[sid] = (
                sub["tick"].to_numpy(dtype=np.float64),
                sub["yaw"].to_numpy(dtype=np.float64),
            )
    for _, row in df.iterrows():
        x = _finite_or_none(row.get("user_X"))
        y = _finite_or_none(row.get("user_Y"))
        if x is None:
            continue  # Team 0 shooters have no position; skip silently
        sid = _text(row.get("user_steamid", ""))
        tick = int(row.get("tick", 0) or 0)
        ya = None
        series = yaw_by_sid.get(sid)
        if series is not None and len(series[0]):
            ya = float(np.interp(tick, series[0], series[1]))
        out.append(
            {
                "tick": tick,
                "x": round(x, 1),
                "y": round(y, 1),
                "sid": sid,
                "wi": weapons.index(_short_weapon(_text(row.get("weapon", "")))),
                # 5° buckets, same quantization as snapshot yaw
                **({"ya": int(round(ya / 5.0) * 5) % 360} if ya is not None else {}),
            }
        )
    out.sort(key=lambda s: s["tick"])
    return out


_ECON_EMPTY = {"spend": 0, "weapons": [], "nades": 0}


def _economy_events(demo: ParsedDemo, weapons: _WeaponTable) -> dict:
    """Per-round-per-player purchase summary from item_purchase.

    Delegates to analysis.economy.build_purchase_log — the shared aggregation
    consumed by both this layers artifact and the EconomyModule (M7 refactor).
    """
    from cs_analyzer.analysis.economy import build_purchase_log

    rounds: dict[str, dict[str, dict]] = {}
    for rnd, players in build_purchase_log(demo).items():
        bucket_out: dict[str, dict] = {}
        for sid, bucket in players.items():
            bucket_out[sid] = {
                "spend": bucket["spend"],
                "weapons": [weapons.index(w) for w in bucket["weapons"]],
                "nades": bucket["nades"],
            }
        rounds[str(rnd)] = bucket_out
    return {"rounds": rounds}


def build_and_save_layers(demo: ParsedDemo, out_dir: Path,
                          keys: tuple[str, ...] = LAYER_KEYS) -> tuple[Path, int]:
    payload = build_viewer_layers(demo, keys)
    path = viewer_layers_path(demo.metadata.demo_hash, out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    size = len(text.encode("utf-8"))
    logger.info("viewer-layers %s (%s): %.2f MB raw",
                demo.metadata.demo_hash[:12], ",".join(keys), size / 1e6)
    return path, size
