"""Duel (engagement-level) win model (对枪模型, research Round 2).

口径（docs/research-ledger.md，用户已批准的计划送审表 B）：

- **样本**：每回合每对敌对玩家的**首次伤害事件**建一条样本——与 aim_science
  的 engagement 定义一致：(attacker, victim, victim-life) 唯一。
- **标签**：本回合内**先死者**归谁。受伤者先死 → 攻击方胜（y=1）；攻击者
  先死 → y=0。**排除**（不判定）：
    1) 首伤后双方本回合都没死（回合结束仍存活）；
    2) 双方同 tick 死亡（同亡，无法定先后）；
    3) 任一方死于第三方之手（交战被打断）；
    4) 判定窗口超过 DUEL_WINDOW_SEC=15s（被打断后的超长尾事件不归属本交战）。
- **特征**（首伤 tick 采集，全部为首伤时刻可得信息，无未来泄露）：
    distance        player_hurt.distance（demoparser2 实证为米）
    hp_diff         攻击方 HP − 受击方 HP（ticks health 列）
    armor_diff      攻击方护甲 − 受击方护甲（ticks armor 列）
    weapon_class    攻击方武器类别（canonical → category，one-hot 对位由
                    web 聚合层展开；这里存类别码）
    att_stopped     攻击方开火时速度 < STOP_VELOCITY
    vic_stopped     受击方速度 < STOP_VELOCITY
    att_preaim_deg  攻击方预瞄偏移（复用 aim_science 的视角校准 + 24tick 前采样）
    vic_blinded     受击方在首伤前 BLIND_WINDOW_SEC 内被闪过（player_blind）
    hitgroup_head   首伤命中部位是头部
    att_rating      攻击方本 demo Rating21（"谁在开枪"的强度代理）
    vic_rating      受击方本 demo Rating21
    side            攻击方阵营（T=1/CT=0）

诚实边界：无地图几何 → 无视线遮挡判定，"被偷"只能用受击方视角朝向近似
（vic 视线与攻击方方向的夹角，vic_facing_away），页面脚注照实写明。

纯 numpy / pydantic，无新依赖；tick 缺列时特征 fail-soft 为 0 并记 note。
"""
from __future__ import annotations

import bisect

import numpy as np
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid, round_player_sides
from cs_analyzer.analysis.weapons import category as weapon_category
from cs_analyzer.model.parsed_demo import ParsedDemo

#: Engagement resolution window: deaths later than this after the first hit
#: are attributed to *later* fights, not this engagement (approved 口径: 15s).
DUEL_WINDOW_SEC = 15.0
#: A blind landing within this window before the first hit counts as "flashed".
BLIND_WINDOW_SEC = 2.5
#: aim_science shared constants (kept in sync by import, not by value).
from cs_analyzer.analysis.aim_science import (  # noqa: E402
    EYE_Z, PREAIM_LEAD_TICKS, STOP_VELOCITY, _angle_deg, _view_vector,
)

#: weapon category codes (fixed order; web layer expands one-hots)
WEAPON_CLASSES = ("rifle", "sniper", "pistol", "smg", "heavy", "unknown")
#: R3 H-A: a fire tick within this window before the first hit (and before
#: the hit tick itself) marks "was already firing" for each member.
FIRED_BEFORE_SEC = 3.0


class DuelSample(BaseModel):
    """One first-hit engagement with its (attacker-perspective) label."""

    round: int
    tick: int
    attacker: str
    victim: str
    y: int  # 1 = attacker won (victim died first), 0 = attacker died first
    # features (首伤 tick 采集)
    distance: float = 0.0
    hp_diff: float = 0.0
    armor_diff: float = 0.0
    weapon_cls: str = "unknown"
    att_stopped: int = 0
    vic_stopped: int = 0
    att_preaim_deg: float = 0.0
    vic_blinded: int = 0
    vic_facing_away: float = 0.0  # victim view vs attacker direction (deg)
    hitgroup_head: int = 0
    att_rating: float = 0.0
    vic_rating: float = 0.0
    side: int = 0  # attacker T=1 / CT=0
    # R3 H-A: fired within FIRED_BEFORE_SEC before the first hit (excluding
    # the hit's own tick)? — "already spraying/pre-firing" vs clean first shot
    att_fired_before: int = 0
    vic_fired_before: int = 0


class DuelModelResult(AnalysisResult):
    samples: list[DuelSample] = Field(default_factory=list)
    n_excluded: dict = Field(default_factory=dict)
    notes: dict = Field(default_factory=dict)


def _feature_row(s: DuelSample) -> list[float]:
    """Fixed-order feature vector (duelmo shard row contract)."""
    row = [float(s.distance), float(s.hp_diff), float(s.armor_diff),
           float(s.att_stopped), float(s.vic_stopped),
           float(s.att_preaim_deg), float(s.vic_blinded),
           float(s.vic_facing_away), float(s.hitgroup_head),
           float(s.att_rating), float(s.vic_rating), float(s.side)]
    row.extend(1.0 if s.weapon_cls == wc else 0.0
               for wc in WEAPON_CLASSES[1:])  # rifle is the baseline
    row.append(float(s.att_fired_before))
    row.append(float(s.vic_fired_before))
    return row


def duel_feature_names() -> list[str]:
    names = ["distance", "hp_diff", "armor_diff", "att_stopped", "vic_stopped",
             "att_preaim_deg", "vic_blinded", "vic_facing_away",
             "hitgroup_head", "att_rating", "vic_rating", "side"]
    names.extend(f"weapon_{wc}" for wc in WEAPON_CLASSES[1:])
    names.extend(["att_fired_before", "vic_fired_before"])
    return names


class _TickState:
    """Per-player (tick -> alive/hp/armor/pos/view/vel) single-point lookups.

    Same L0 contiguous-run pattern as aim_science / win_probability V2.
    """

    def __init__(self, ticks) -> None:
        self.usable = False
        need = {"steamid", "tick", "is_alive", "health", "armor",
                "X", "Y", "Z", "pitch", "yaw", "velocity"}
        if ticks is None or ticks.empty or not need.issubset(set(ticks.columns)):
            return
        cols = ["steamid", "tick", "is_alive", "health", "armor",
                "X", "Y", "Z", "pitch", "yaw", "velocity"]
        t = ticks[cols].sort_values(["steamid", "tick"], kind="stable")
        sid = t["steamid"].to_numpy()
        self.tick_arr = t["tick"].to_numpy(dtype=np.int64)
        self.alive = t["is_alive"].to_numpy(dtype=float)
        self.hp = t["health"].to_numpy(dtype=float)
        self.armor = t["armor"].to_numpy(dtype=float)
        self.x = t["X"].to_numpy(dtype=float)
        self.y = t["Y"].to_numpy(dtype=float)
        self.z = t["Z"].to_numpy(dtype=float)
        self.pitch = t["pitch"].to_numpy(dtype=float)
        self.yaw = t["yaw"].to_numpy(dtype=float)
        self.vel = t["velocity"].to_numpy(dtype=float)
        bounds = np.flatnonzero(np.r_[True, sid[1:] != sid[:-1]])
        edges = np.r_[bounds, len(sid)]
        self.runs = {str(sid[b]): (int(b), int(e))
                     for b, e in zip(bounds, edges[1:])}
        self.usable = True

    def idx(self, sid: str, tick: int) -> int | None:
        run = self.runs.get(sid)
        if run is None:
            return None
        i0, i1 = run
        i = i0 + int(np.searchsorted(self.tick_arr[i0:i1], tick, side="right")) - 1
        if i < i0:
            return None
        return i

    def state(self, sid: str, tick: int) -> dict | None:
        i = self.idx(sid, tick)
        if i is None:
            return None
        return {"alive": self.alive[i] > 0.5, "hp": float(self.hp[i]),
                "armor": float(self.armor[i]), "x": self.x[i], "y": self.y[i],
                "z": self.z[i], "pitch": self.pitch[i], "yaw": self.yaw[i],
                "vel": float(self.vel[i])}


def compute_duel_model(demo: ParsedDemo, ctx: AnalysisContext | None = None) -> DuelModelResult:
    res = DuelModelResult(module="duel_model", demo_hash=demo.metadata.demo_hash)
    rounds = demo.regular_rounds
    if not rounds:
        res.notes["skipped"] = "no regular rounds"
        return res

    r21 = None
    if ctx is not None:
        r21 = ctx.get("ratings21")
    rating_of = ({p.steamid: p.Rating21 for p in r21.players}
                 if r21 is not None else {})

    tick_rate = float(demo.metadata.tick_rate or 64)
    window_ticks = int(DUEL_WINDOW_SEC * tick_rate)
    blind_ticks = int(BLIND_WINDOW_SEC * tick_rate)

    start = rounds[0].start_tick
    round_starts = [r.start_tick for r in rounds]
    round_numbers = [r.number for r in rounds]
    round_bounds = {r.number: (r.start_tick, r.end_tick) for r in rounds}

    def round_of(tick: int) -> int | None:
        i = bisect.bisect_right(round_starts, tick) - 1
        if i < 0:
            return None
        return round_numbers[i]

    side_map = round_player_sides(demo)
    ts = _TickState(demo.ticks)

    def side_at(sid: str, tick: int) -> str:
        rn = round_of(tick)
        return side_map.get(rn, {}).get(sid, "") if rn else ""

    # ---- events ----
    hurt = demo.events.get("player_hurt")
    deaths = demo.events.get("player_death")
    blinds = demo.events.get("player_blind")
    if hurt is None or hurt.empty or deaths is None or deaths.empty:
        res.notes["skipped"] = "no player_hurt/player_death events"
        return res

    # deaths per player sorted (life segmentation + window logic)
    vic_deaths: dict[str, list[int]] = {}
    d = deaths[deaths["tick"] >= start]
    for sid, t in zip(d["user_steamid"], d["tick"]):
        s = clean_sid(sid)
        if s:
            vic_deaths.setdefault(s, []).append(int(t))
    for v in vic_deaths.values():
        v.sort()

    def life_index(vic: str, tick: int) -> int:
        return bisect.bisect_left(vic_deaths.get(vic, []), tick)

    # enemy first-hurt engagements (aim_science definition); capture the
    # first-hit row's weapon/hitgroup/distance ONCE (O(n) — re-querying the
    # hurt frame per engagement was an O(n²) landmine)
    engagements: dict[tuple[str, str, int], tuple[int, dict]] = {}
    h = hurt[hurt["tick"] >= start]
    for _, row in h.iterrows():
        att = clean_sid(row.get("attacker_steamid", ""))
        vic = clean_sid(row.get("user_steamid", ""))
        if not att or not vic or att == vic:
            continue
        t = int(row["tick"])
        if side_at(att, t) == side_at(vic, t):
            continue  # team damage / unresolved sides
        key = (att, vic, life_index(vic, t))
        if key not in engagements:  # keep the FIRST hurt row per engagement
            engagements[key] = (t, {
                "weapon": str(row.get("weapon", "") or ""),
                "hitgroup": str(row.get("hitgroup", "") or ""),
                "distance": row.get("distance"),
            })

    # per-attacker sorted fire ticks (preaim lead sample needs a state check)
    fires = demo.events.get("weapon_fire")
    shots: dict[str, list[int]] = {}
    if fires is not None and not fires.empty:
        f = fires[fires["tick"] >= start]
        for sid, t in zip(f["user_steamid"], f["tick"]):
            s = clean_sid(sid)
            if s:
                shots.setdefault(s, []).append(int(t))
        for v in shots.values():
            v.sort()

    # blinds per victim: sorted detonate→victim pairs approximated by
    # player_blind events on the victim (event carries attacker + duration;
    # we only need "was the victim blinded recently before the first hit")
    blind_ticks_by_vic: dict[str, list[int]] = {}
    if blinds is not None and not blinds.empty:
        b = blinds[blinds["tick"] >= start]
        for sid, t in zip(b["user_steamid"], b["tick"]):
            s = clean_sid(sid)
            if s:
                blind_ticks_by_vic.setdefault(s, []).append(int(t))
        for v in blind_ticks_by_vic.values():
            v.sort()

    # view-convention calibration — identical to aim_science (four candidates
    # scored on median aim-at-damage angle; the demo-level winner is reused)
    yaw_mirror, pitch_sign = _calibrate_convention(
        engagements, ts, rounds, round_numbers)

    def view(sid: str, tick: int) -> np.ndarray | None:
        s = ts.state(sid, tick)
        if s is None:
            return None
        return _view_vector(s["yaw"], s["pitch"], yaw_mirror, pitch_sign)

    # per-round death attribution: (round, player) -> (death_tick, killer)
    death_info: dict[tuple[int, str], tuple[int, str]] = {}
    for _, row in d.iterrows():
        rn = round_of(int(row["tick"]))
        vic = clean_sid(row.get("user_steamid", ""))
        att = clean_sid(row.get("attacker_steamid", ""))
        if rn is not None and vic:
            death_info[(rn, vic)] = (int(row["tick"]), att)

    excluded = {"no_death_in_round": 0, "same_tick": 0, "third_party": 0,
                "out_of_window": 0, "no_tick_state": 0}

    for (att, vic, _life), (t0, first_hit) in sorted(engagements.items()):
        rn = round_of(t0)
        if rn is None:
            continue
        r0s, r0e = round_bounds[rn]
        if not ts.usable:
            excluded["no_tick_state"] += 1
            continue
        # state at the first-hit tick; on a lethal first hit the victim's
        # is_alive already flips False on the SAME tick — retry at t0-1 so
        # one-tap duels (the cleanest y=1 samples) are not silently dropped
        sa0 = ts.state(att, t0)
        sv0 = ts.state(vic, t0)
        if (sa0 is None or sv0 is None or not sa0["alive"] or not sv0["alive"]) \
                and t0 - 1 >= r0s:
            sa1 = ts.state(att, t0 - 1)
            sv1 = ts.state(vic, t0 - 1)
            if sa1 and sv1 and sa1["alive"] and sv1["alive"]:
                sa0, sv0 = sa1, sv1
        if sa0 is None or sv0 is None or not sa0["alive"] or not sv0["alive"]:
            excluded["no_tick_state"] += 1
            continue

        # ---- label: who died first (within the round + window) ----
        da = death_info.get((rn, att))
        dv = death_info.get((rn, vic))
        if da is None and dv is None:
            excluded["no_death_in_round"] += 1
            continue
        if da is not None and dv is not None:
            if da[0] == dv[0]:
                excluded["same_tick"] += 1
                continue
            if min(da[0], dv[0]) > t0 + window_ticks:
                excluded["out_of_window"] += 1
                continue
        elif da is None:
            if dv[0] > t0 + window_ticks or dv[0] > r0e:
                excluded["out_of_window"] += 1
                continue
        else:  # dv is None — attacker died later in the round
            if da[0] > t0 + window_ticks or da[0] > r0e:
                excluded["out_of_window"] += 1
                continue
        first_death_tick = da[0] if dv is None else (dv[0] if da is None else min(da[0], dv[0]))
        # third-party interruption: the first to die was killed by neither
        # member of this engagement
        killer_at_death = da[1] if (da is not None and da[0] == first_death_tick) else (
            dv[1] if (dv is not None and dv[0] == first_death_tick) else "")
        if killer_at_death not in (att, vic):
            excluded["third_party"] += 1
            continue
        y = 1 if (dv is not None and (da is None or dv[0] < da[0])) else 0

        # ---- features at t0 ----
        dist = float(np.hypot(sv0["x"] - sa0["x"], sv0["y"] - sa0["y"]))
        # player_hurt.distance is meters (demoparser2 实证); tick XY hypot is
        # the fallback when the event column is missing/zero
        ev_dist = first_hit["distance"]
        try:
            if ev_dist is not None and float(ev_dist) > 0:
                dist = float(ev_dist)
        except (TypeError, ValueError):
            pass

        # preaim: view-vs-target angle PREAIM_LEAD_TICKS before t0
        tp = t0 - PREAIM_LEAD_TICKS
        preaim = 0.0
        if tp >= r0s:
            sap = ts.state(att, tp)
            svp = ts.state(vic, tp)
            if sap and svp and sap["alive"] and svp["alive"]:
                dirv = np.array([svp["x"] - sap["x"], svp["y"] - sap["y"],
                                 (svp["z"] + EYE_Z) - (sap["z"] + EYE_Z)])
                if float(np.linalg.norm(dirv)) > 1:
                    fwd = _view_vector(sap["yaw"], sap["pitch"], yaw_mirror, pitch_sign)
                    preaim = _angle_deg(fwd, dirv)

        # victim facing away: victim's view vs victim→attacker direction
        facing = 180.0
        dir_va = np.array([sa0["x"] - sv0["x"], sa0["y"] - sv0["y"],
                           (sa0["z"] + EYE_Z) - (sv0["z"] + EYE_Z)])
        if float(np.linalg.norm(dir_va)) > 1:
            v_fwd = view(vic, t0)
            if v_fwd is not None:
                facing = _angle_deg(v_fwd, dir_va)

        blind_hit = 0
        bt = blind_ticks_by_vic.get(vic)
        if bt:
            i = bisect.bisect_right(bt, t0) - 1
            if i >= 0 and t0 - bt[i] <= blind_ticks:
                blind_hit = 1

        # R3 H-A: "already firing" in the 3s before the first hit (strictly
        # before t0 — the hit's own shot fires at/after t0)
        fire_win = int(FIRED_BEFORE_SEC * tick_rate)

        def _fired_before(sid: str) -> int:
            sl = shots.get(sid)
            if not sl:
                return 0
            i = bisect.bisect_left(sl, t0) - 1
            return 1 if (i >= 0 and t0 - fire_win <= sl[i] < t0) else 0

        wpn_raw = first_hit["weapon"]
        wcls = weapon_category(wpn_raw) if wpn_raw else "unknown"
        if wcls not in WEAPON_CLASSES:
            wcls = "unknown"

        res.samples.append(DuelSample(
            round=rn, tick=t0, attacker=att, victim=vic, y=y,
            distance=round(dist, 2),
            hp_diff=sa0["hp"] - sv0["hp"],
            armor_diff=sa0["armor"] - sv0["armor"],
            weapon_cls=wcls,
            att_stopped=1 if sa0["vel"] < STOP_VELOCITY else 0,
            vic_stopped=1 if sv0["vel"] < STOP_VELOCITY else 0,
            att_preaim_deg=round(float(preaim), 2),
            vic_blinded=blind_hit,
            vic_facing_away=round(float(facing), 2),
            hitgroup_head=1 if first_hit["hitgroup"].lower() == "head" else 0,
            att_rating=rating_of.get(att, 0.0),
            vic_rating=rating_of.get(vic, 0.0),
            side=1 if side_at(att, t0) == "T" else 0,
            att_fired_before=_fired_before(att),
            vic_fired_before=_fired_before(vic),
        ))

    res.n_excluded = excluded
    res.notes = {
        "sample_def": "每回合每对敌对玩家首次伤害建一条样本（aim_science engagement 同源）",
        "label_def": "本回合先死者归谁；双方都没死/同亡/第三方打断/超 15s 窗口不判定",
        "boundaries": "无地图几何（无视线遮挡判定，被偷≈受击方视线夹角大）；64tick ±1 tick=±15.6ms",
    }
    return res


def _calibrate_convention(engagements, ts: _TickState, rounds, round_numbers):
    """aim_science 同款四候选视角校准（伤害时刻夹角中位数应≈0）。

    Fail-soft: no usable state → Source 标准约定 (False, 1.0)。
    """
    del round_numbers  # signature parity with the aim_science caller shape
    if not ts.usable or not engagements:
        return False, 1.0
    sample = [(k, t0) for k, (t0, _row) in list(engagements.items())[:200]]
    best = None
    for yaw_mirror in (False, True):
        for pitch_sign in (1.0, -1.0):
            vals = []
            for (att, vic, _life), t0 in sample:
                sa = ts.state(att, t0)
                sv = ts.state(vic, t0)
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
        return False, 1.0
    return best[1], best[2]


@register_module
class DuelModelModule(AnalysisModule):
    name = "duel_model"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        return compute_duel_model(demo, ctx)
