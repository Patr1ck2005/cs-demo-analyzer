"""Aim science (枪法科学, Phase R3) — Leetify-style aim metrics from tick data.

All inputs come from the EXISTING 1.8.0 cache (pitch/yaw/X/Y/Z/velocity/
is_alive ticks + weapon_fire/player_hurt/player_death events) — zero
re-parse, PARSER_VERSION untouched.

Metrics (per player, per demo):
- 预瞄偏移 preaim: 3D angle between the attacker's view vector and the
  attacker→victim direction sampled PREAIM_LEAD_TICKS before the FIRST
  enemy damage of an engagement (first player_hurt attacker→victim within
  the victim's current life). Crosshair discipline proxy.
- 反击枪延迟 counter_shot: time from taking the first enemy damage of a
  life to the player's first weapon_fire (≤ REACTION_WINDOW). A hard,
  visible event — the honest "reaction" proxy (no LOS data exists).
- 急停纪律 stopped_fire: share of shots fired with velocity < STOP_VELOCITY,
  plus engagement win rate split stopped vs moving.
- fire→damage conversion: shots that produced damage within 32 ticks.

Honest boundaries (rendered on the page):
- No map geometry → no line-of-sight/occlusion check. "Engagement" = first
  damage of the duel; preaim is sampled Δt BEFORE that damage.
- 64-tick sampling → ±1 tick = ±15.6 ms on every latency metric.
- Angle convention is auto-calibrated per demo: four (yaw-mirror × pitch-
  sign) candidates are scored on the median view-to-target angle AT the
  damage event (should be near zero under the true convention) and the
  winner is used everywhere. The calibration diagnostic ships as
  ``aim_dmg_med_deg`` — if it is large, treat preaim as unreliable.
"""
from __future__ import annotations

import bisect
import math

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid, round_player_sides
from cs_analyzer.model.parsed_demo import ParsedDemo

PREAIM_LEAD_TICKS = 24      # ~0.375 s at 64 tick
STOP_VELOCITY = 50.0        # u/s — below this the player is "stopped"
REACTION_WINDOW_TICKS = 192  # 3 s: a later return-fire is not a reaction
FIRE_DAMAGE_WINDOW_TICKS = 32  # ~0.5 s: shot -> damage
DUEL_KILL_WINDOW_TICKS = 320   # 5 s: engagement win = victim died in window
EYE_Z = 64.0                # both feet-Z get +EYE_Z (cancels for equal height)


class AimScienceResult(AnalysisResult):
    players: list[dict] = Field(default_factory=list)
    samples: dict[str, dict] = Field(default_factory=dict)
    notes: dict = Field(default_factory=dict)


def _rad(deg: float) -> float:
    return deg * math.pi / 180.0


def _view_vector(yaw: float, pitch: float, yaw_mirror: bool, pitch_sign: float) -> np.ndarray:
    """Source-convention view vector with adjustable conventions.

    Source: forward = (cos p · cos y, cos p · sin y, −sin p), pitch positive
    = down. ``yaw_mirror`` handles parsers that report yaw mirrored around
    the Y axis; ``pitch_sign`` handles pitch positive = up.
    """
    y = 360.0 - yaw if yaw_mirror else yaw
    p = pitch_sign * pitch
    cp, sp = math.cos(_rad(p)), math.sin(_rad(p))
    cy, sy = math.cos(_rad(y)), math.sin(_rad(y))
    return np.array([cp * cy, cp * sy, -sp])


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 0:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(a, b)) / denom))))


def compute_aim_science(demo: ParsedDemo) -> AimScienceResult:
    res = AimScienceResult(module="aim_science", demo_hash=demo.metadata.demo_hash)
    ticks = demo.ticks
    need = {"steamid", "tick", "X", "Y", "Z", "pitch", "yaw", "velocity", "is_alive"}
    if ticks is None or ticks.empty or not need.issubset(set(ticks.columns)):
        res.notes["skipped"] = "tick table missing required columns"
        return res
    rounds = demo.regular_rounds
    if not rounds:
        res.notes["skipped"] = "no regular rounds"
        return res

    tick_rate = float(demo.metadata.tick_rate or 64)
    start = rounds[0].start_tick
    round_starts = [r.start_tick for r in rounds]
    round_numbers = [r.number for r in rounds]

    def round_of(tick: int) -> int | None:
        i = bisect.bisect_right(round_starts, tick) - 1
        if i < 0:
            return None
        return round_numbers[i]

    # ---- per-player contiguous sorted tick runs (L0 pattern) ----
    cols = ["steamid", "tick", "X", "Y", "Z", "pitch", "yaw", "velocity", "is_alive"]
    t_sorted = ticks[cols].sort_values(["steamid", "tick"], kind="stable")
    sid_arr = t_sorted["steamid"].to_numpy()
    tick_arr = t_sorted["tick"].to_numpy(dtype=np.int64)
    x_arr = t_sorted["X"].to_numpy(dtype=float)
    y_arr = t_sorted["Y"].to_numpy(dtype=float)
    z_arr = t_sorted["Z"].to_numpy(dtype=float)
    yaw_arr = t_sorted["yaw"].to_numpy(dtype=float)
    pitch_arr = t_sorted["pitch"].to_numpy(dtype=float)
    vel_arr = t_sorted["velocity"].to_numpy(dtype=float)
    alive_arr = t_sorted["is_alive"].to_numpy(dtype=float)
    boundaries = np.flatnonzero(np.r_[True, sid_arr[1:] != sid_arr[:-1]])
    edges = np.r_[boundaries, len(sid_arr)]
    runs: dict[str, tuple[int, int]] = {}
    for b, e in zip(boundaries, edges[1:]):
        runs[str(sid_arr[b])] = (int(b), int(e))

    def state_at(sid: str, tick: int) -> dict | None:
        run = runs.get(sid)
        if run is None:
            return None
        i0, i1 = run
        i = i0 + int(np.searchsorted(tick_arr[i0:i1], tick, side="right")) - 1
        if i < i0:
            return None
        return {"x": x_arr[i], "y": y_arr[i], "z": z_arr[i],
                "yaw": yaw_arr[i], "pitch": pitch_arr[i],
                "vel": vel_arr[i], "alive": alive_arr[i] > 0.5}

    # ---- events ----
    events = demo.events
    hurt = events.get("player_hurt")
    deaths = events.get("player_death")
    fires = events.get("weapon_fire")

    # shots per shooter: sorted regulation fire ticks
    shots: dict[str, list[int]] = {}
    if fires is not None and not fires.empty:
        f = fires[fires["tick"] >= start]
        for sid, t in zip(f["user_steamid"], f["tick"]):
            s = clean_sid(sid)
            if s:
                shots.setdefault(s, []).append(int(t))
        for v in shots.values():
            v.sort()

    # enemy hurts: [(tick, att, vic)] with sides known & different
    side_map = round_player_sides(demo)

    def side_at(sid: str, tick: int) -> str:
        rn = round_of(tick)
        return side_map.get(rn, {}).get(sid, "") if rn else ""

    enemy_hurts: list[tuple[int, str, str]] = []
    if hurt is not None and not hurt.empty:
        h = hurt[hurt["tick"] >= start]
        for _, row in h.iterrows():
            att = clean_sid(row.get("attacker_steamid", ""))
            vic = clean_sid(row.get("user_steamid", ""))
            if not att or not vic or att == vic:
                continue
            if side_at(att, int(row["tick"])) == side_at(vic, int(row["tick"])):
                continue  # team damage / unresolved sides — skip
            enemy_hurts.append((int(row["tick"]), att, vic))
    enemy_hurts.sort()

    # deaths per victim (life segmentation)
    vic_deaths: dict[str, list[int]] = {}
    if deaths is not None and not deaths.empty:
        d = deaths[deaths["tick"] >= start]
        for sid, t in zip(d["user_steamid"], d["tick"]):
            s = clean_sid(sid)
            if s:
                vic_deaths.setdefault(s, []).append(int(t))
        for v in vic_deaths.values():
            v.sort()

    def life_index(vic: str, tick: int) -> int:
        return bisect.bisect_left(vic_deaths.get(vic, []), tick)

    # engagement = first enemy hurt per (attacker, victim, victim-life)
    engagements: dict[tuple[str, str, int], int] = {}
    for t, att, vic in enemy_hurts:
        engagements.setdefault((att, vic, life_index(vic, t)), t)

    # ---- convention calibration: median aim angle AT damage should be ~0 ----
    sample = list(engagements.items())[:200]
    best = None
    for yaw_mirror in (False, True):
        for pitch_sign in (1.0, -1.0):
            vals = []
            for (att, vic, _life), t0 in sample:
                sa = state_at(att, t0)
                sv = state_at(vic, t0)
                if not sa or not sv or not sa["alive"] or not sv["alive"]:
                    continue
                dirv = np.array([sv["x"] - sa["x"], sv["y"] - sa["y"],
                                 (sv["z"] + EYE_Z) - (sa["z"] + EYE_Z)])
                fwd = _view_vector(sa["yaw"], sa["pitch"], yaw_mirror, pitch_sign)
                vals.append(_angle_deg(fwd, dirv))
            med = float(np.median(vals)) if vals else 180.0
            if best is None or med < best[0]:
                best = (med, yaw_mirror, pitch_sign)
    if best is None:
        res.notes["skipped"] = "no calibratable engagements"
        return res
    _, yaw_mirror, pitch_sign = best
    res.notes["calibration"] = {"yaw_mirror": yaw_mirror, "pitch_sign": pitch_sign,
                                "aim_at_damage_med_deg": round(best[0], 2)}

    def view(sid: str, tick: int) -> np.ndarray | None:
        s = state_at(sid, tick)
        if s is None:
            return None
        return _view_vector(s["yaw"], s["pitch"], yaw_mirror, pitch_sign)

    # ---- per-player accumulators ----
    P = {}  # sid -> sample lists + counters

    def P_(sid: str) -> dict:
        return P.setdefault(sid, {
            "preaim": [], "preaim_pitch": [], "preaim_lt10": [],
            "aim_dmg": [], "counter_s": [], "counter_nofire": 0,
            "duels_stopped": [], "duels_moving": [],
            "shots": 0, "stopped_shots": 0, "dmg_shots": 0,
        })

    roster = {p.steamid: p.name for p in demo.players}

    # preaim + duel outcome per engagement
    for (att, vic, _life), t0 in engagements.items():
        rn = round_of(t0)
        if rn is None:
            continue
        r0 = rounds[round_numbers.index(rn)]
        t = t0 - PREAIM_LEAD_TICKS
        if t < r0.start_tick:
            continue  # sample would fall into freeze time
        sa = state_at(att, t)
        sv = state_at(vic, t)
        sa0 = state_at(att, t0)
        if not sa or not sv or not sa0 or not sa["alive"] or not sv["alive"]:
            continue
        pa = P_(att)
        dirv = np.array([sv["x"] - sa["x"], sv["y"] - sa["y"],
                         (sv["z"] + EYE_Z) - (sa["z"] + EYE_Z)])
        norm = float(np.linalg.norm(dirv))
        if norm <= 1:
            continue
        fwd = view(att, t)
        ang = _angle_deg(fwd, dirv)
        # vertical: elevation of the target vs the implied view elevation
        elev = math.degrees(math.asin(max(-1.0, min(1.0, dirv[2] / norm))))
        fwd_elev = math.degrees(math.asin(max(-1.0, min(1.0, float(fwd[2])))))
        pa["preaim"].append(round(ang, 2))
        pa["preaim_pitch"].append(round(abs(elev - fwd_elev), 2))
        pa["preaim_lt10"].append(1 if ang < 10.0 else 0)
        # engagement outcome + movement bucket at t0
        win = False
        vd = vic_deaths.get(vic, [])
        j = bisect.bisect_right(vd, t0)
        if j < len(vd) and vd[j] <= t0 + DUEL_KILL_WINDOW_TICKS:
            ad = vic_deaths.get(att, [])
            k = bisect.bisect_right(ad, t0)
            if not (k < len(ad) and ad[k] < vd[j]):
                win = True  # victim died in window and attacker survived that long
        (pa["duels_stopped"] if sa0["vel"] < STOP_VELOCITY else pa["duels_moving"]).append(1 if win else 0)
        # calibration diagnostic: aim angle at the damage event itself
        dir0 = np.array([sv["x"] - sa0["x"], sv["y"] - sa0["y"],
                         (sv["z"] + EYE_Z) - (sa0["z"] + EYE_Z)])
        if float(np.linalg.norm(dir0)) > 1:
            pa["aim_dmg"].append(round(_angle_deg(view(att, t0), dir0), 2))

    # counter-shot latency: first enemy damage of a victim life -> first fire
    first_hurt_in_life: dict[tuple[str, int], int] = {}
    for t, att, vic in enemy_hurts:
        first_hurt_in_life.setdefault((vic, life_index(vic, t)), t)
    for (vic, _life), th in first_hurt_in_life.items():
        pv = P_(vic)
        s = shots.get(vic)
        i = bisect.bisect_right(s, th) if s else 0
        if i < len(s) and s[i] <= th + REACTION_WINDOW_TICKS:
            pv["counter_s"].append(round((s[i] - th) / tick_rate, 3))
        else:
            pv["counter_nofire"] += 1

    # fire -> damage conversion + stopped-fire discipline
    enemy_hurt_ticks_by_att: dict[str, list[int]] = {}
    for t, att, _vic in enemy_hurts:
        enemy_hurt_ticks_by_att.setdefault(att, []).append(t)
    for sid, sl in shots.items():
        reg = [t for t in sl if t >= start]
        if not reg:
            continue
        p = P_(sid)
        p["shots"] += len(reg)
        for t in reg:
            s = state_at(sid, t)
            if s and s["vel"] < STOP_VELOCITY:
                p["stopped_shots"] += 1
        hurts = enemy_hurt_ticks_by_att.get(sid, [])
        if hurts:
            used: set[int] = set()
            for t in reg:
                i = bisect.bisect_left(hurts, t)
                while i < len(hurts) and i in used:
                    i += 1
                if i < len(hurts) and hurts[i] <= t + FIRE_DAMAGE_WINDOW_TICKS:
                    used.add(i)
                    p["dmg_shots"] += 1

    # ---- assemble ----
    def med(vals: list[float]) -> float | None:
        return round(float(np.median(vals)), 2) if vals else None

    for sid, p in P.items():
        n_pre = len(p["preaim"])
        n_cnt = len(p["counter_s"])
        n_duel_s = len(p["duels_stopped"])
        n_duel_m = len(p["duels_moving"])
        row = {
            "steamid": sid, "name": roster.get(sid, sid),
            "n_shots": p["shots"],
            "stopped_fire_rate": round(p["stopped_shots"] / p["shots"], 3) if p["shots"] else None,
            "fire_damage_rate": round(p["dmg_shots"] / p["shots"], 3) if p["shots"] else None,
            "preaim_n": n_pre,
            "preaim_med_deg": med(p["preaim"]),
            "preaim_pitch_med_deg": med(p["preaim_pitch"]),
            "preaim_lt10_rate": round(sum(p["preaim_lt10"]) / n_pre, 3) if n_pre else None,
            "aim_dmg_med_deg": med(p["aim_dmg"]),
            "counter_n": n_cnt + p["counter_nofire"],
            "counter_med_s": med(p["counter_s"]),
            "counter_fast_rate": (
                round(sum(1 for s_ in p["counter_s"] if s_ <= 0.5) / (n_cnt + p["counter_nofire"]), 3)
                if (n_cnt + p["counter_nofire"]) else None),
            "duel_stopped_n": n_duel_s,
            "duel_stopped_wins": sum(p["duels_stopped"]),
            "duel_moving_n": n_duel_m,
            "duel_moving_wins": sum(p["duels_moving"]),
        }
        res.players.append(row)
        res.samples[sid] = {
            "steamid": sid, "name": row["name"],
            "preaim": p["preaim"], "preaim_pitch": p["preaim_pitch"],
            "preaim_lt10": p["preaim_lt10"], "aim_dmg": p["aim_dmg"],
            "counter_s": p["counter_s"], "counter_nofire": p["counter_nofire"],
            "duels_stopped": p["duels_stopped"], "duels_moving": p["duels_moving"],
            "shots": p["shots"], "stopped_shots": p["stopped_shots"],
            "dmg_shots": p["dmg_shots"],
        }
    res.players.sort(key=lambda r: -(r["n_shots"] or 0))
    return res


@register_module
class AimScienceModule(AnalysisModule):
    name = "aim_science"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        return compute_aim_science(demo)
