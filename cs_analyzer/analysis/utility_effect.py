"""Utility effectiveness (道具效用评估, Phase F M8).

Flash value: per flashbang_detonate by player P, sum the blind_duration of
ENEMIES blinded within a ±window; friendly blinds count at half value.
Smoke denial: kills where the victim stood inside a live smoke zone while the
killer was outside it (烟中击杀).
"""
from __future__ import annotations

import logging
import math

from pydantic import Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid, round_player_sides
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

FLASH_WINDOW_TICKS = 96   # ±1.5s at 64 tick
SMOKE_RADIUS = 120        # world units
FRIENDLY_BLIND_WEIGHT = 0.5

# ---- Phase R4 道具执行科学 ----
EXEC_SUPPORT_WINDOW_TICKS = 192  # 3s: blinded enemy must die within this
LATE_AFTER_TICKS = 320           # 5s after the round's execute anchor
_MOLLY_KEYS = ("inferno", "molotov", "incgrenade")


def _finite(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _xy(row, *names) -> float | None:
    """First finite float among alternate column names (0.42 uses lowercase
    x/y for grenade events; deaths keep uppercase user_X/attacker_X)."""
    for n in names:
        v = _finite(row.get(n))
        if v is not None:
            return v
    return None


class UtilityEffectResult(AnalysisResult):
    # per thrower: flash stats
    flashers: list[dict] = Field(default_factory=list)
    # smoke denial counters per player
    smoke: list[dict] = Field(default_factory=list)
    # L2 additive: map-space spots for the utility-lab heatmap —
    # {x, y, round, side, kind: "smoke"|"kill"}; world coords, fail-soft
    # (rows without X/Y are skipped). No parser change: events already cached.
    smoke_events: list[dict] = Field(default_factory=list)
    # R4 道具执行科学: per-player support-flash / late-utility / molly counters
    exec_players: list[dict] = Field(default_factory=list)
    # R4: per-round smoke-before-contact buckets for the win-rate merge
    # [{round, side, smokes: 0|1|2, won}]  (2 = "2+")
    exec_rounds: list[dict] = Field(default_factory=list)


@register_module
class UtilityEffectModule(AnalysisModule):
    name = "utility_effect"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        # swap-safe per-round side map (Phase I); fall back to a flat
        # whole-demo map for players/rounds the windowed scan can't resolve
        round_sides = round_player_sides(demo)

        def side_at(sid: str, tick: int | None = None) -> str:
            if tick is not None:
                rnd = demo.data.round_at_tick(int(tick))
                if rnd is not None:
                    s = round_sides.get(rnd.number, {}).get(sid, "")
                    if s:
                        return s
                # between rounds / unresolved -> nearest known round
                known = [m.get(sid, "") for m in round_sides.values() if m.get(sid)]
                if len(set(known)) == 1 and known:
                    return known[0]
                return ""
            return ""

        flashers = self._flash_value(demo, side_at)
        smoke, smoke_events = self._smoke_denial(demo, side_at)
        self._fold_flash_assists(demo, flashers)
        exec_players, exec_rounds = self._execute_science(demo, side_at)
        return UtilityEffectResult(
            module=self.name, demo_hash=demo.metadata.demo_hash,
            flashers=flashers, smoke=smoke, smoke_events=smoke_events,
            exec_players=exec_players, exec_rounds=exec_rounds,
        )

    @staticmethod
    def _fold_flash_assists(demo: ParsedDemo, flashers: list[dict]) -> None:
        """F4: player_death.assistedflash credits the flashing teammate.

        Adds `flash_assists` to each thrower row (0 for players absent from
        the flash table but credited by a kill — they get a new row so the
        leaderboard never hides a flash-assist-only performance).
        """
        deaths = demo.events.get("player_death")
        if deaths is None or deaths.empty or "assistedflash" not in deaths.columns:
            return
        counts: dict[str, int] = {}
        names: dict[str, str] = {}
        rounds = demo.regular_rounds
        start_tick = rounds[0].start_tick if rounds else 0
        for _, row in deaths.iterrows():
            tick = int(row.get("tick", 0) or 0)
            if tick < start_tick:
                continue
            if not bool(row.get("assistedflash", False)):
                continue
            assister = clean_sid(row.get("assister_steamid", ""))
            if not assister:
                continue
            counts[assister] = counts.get(assister, 0) + 1
            nm = str(row.get("assister_name", "") or "")
            if nm:
                names.setdefault(assister, nm)
        if not counts:
            return
        by_sid = {f["steamid"]: f for f in flashers}
        for sid, n in counts.items():
            f = by_sid.get(sid)
            if f is None:
                f = {"steamid": sid, "name": names.get(sid) or sid, "throws": 0,
                     "enemy_blind_s": 0.0, "friendly_blind_s": 0.0,
                     "value": 0.0, "value_per_throw": 0.0, "side": ""}
                flashers.append(f)
                by_sid[sid] = f
            f["flash_assists"] = f.get("flash_assists", 0) + n
        flashers.sort(key=lambda x: -x["value"])

    # ---- flash value ----
    def _flash_value(self, demo: ParsedDemo, side_at) -> list[dict]:
        det = demo.events.get("flashbang_detonate")
        blind = demo.events.get("player_blind")
        if blind is None or blind.empty:
            return []
        start_tick = demo.regular_rounds[0].start_tick if demo.regular_rounds else 0
        # index blind rows by tick for windowed scans
        blind_rows = []
        for _, row in blind.iterrows():
            t = int(row.get("tick", 0) or 0)
            vic = clean_sid(row.get("user_steamid", ""))
            dur = _finite(row.get("blind_duration")) or 0.0
            if vic and dur > 0:
                blind_rows.append((t, vic, dur))
        blind_rows.sort()
        bticks = [b[0] for b in blind_rows]

        stats: dict[str, dict] = {}
        for _, row in det.iterrows():
            t = int(row.get("tick", 0) or 0)
            if t < start_tick:
                continue
            thrower = clean_sid(row.get("user_steamid", ""))
            if not thrower:
                continue
            s = stats.setdefault(thrower, {"throws": 0, "enemy_blind_s": 0.0,
                                           "friendly_blind_s": 0.0, "name": ""})
            s["throws"] += 1
            name = str(row.get("user_name", "") or "")
            if name:
                s["name"] = name
            thrower_side = side_at(thrower, t)
            lo = t - FLASH_WINDOW_TICKS
            import bisect
            for i in range(bisect.bisect_left(bticks, lo), len(blind_rows)):
                bt, vic, dur = blind_rows[i]
                if bt > t + FLASH_WINDOW_TICKS:
                    break
                if vic == thrower:
                    continue  # self-blind doesn't count against the throw
                if side_at(vic, bt) == thrower_side and thrower_side:
                    s["friendly_blind_s"] += dur
                elif not side_at(vic, bt) or not thrower_side:
                    pass  # unresolved side on either end — don't guess
                else:
                    s["enemy_blind_s"] += dur
        out = []
        for sid, s in stats.items():
            value = s["enemy_blind_s"] + FRIENDLY_BLIND_WEIGHT * s["friendly_blind_s"]
            out.append({
                "steamid": sid, "name": s["name"] or sid,
                "throws": s["throws"],
                "enemy_blind_s": round(s["enemy_blind_s"], 2),
                "friendly_blind_s": round(s["friendly_blind_s"], 2),
                "value": round(value, 2),
                "value_per_throw": round(value / s["throws"], 2) if s["throws"] else 0.0,
                "side": side_at(sid, None) or "",
            })
        out.sort(key=lambda x: -x["value"])
        return out

    # ---- smoke denial ----
    def _smoke_denial(self, demo: ParsedDemo, side_at) -> tuple[list[dict], list[dict]]:
        det = demo.events.get("smokegrenade_detonate")
        expired = demo.events.get("smokegrenade_expired")
        deaths = demo.events.get("player_death")
        smoke_events: list[dict] = []
        if det is None or det.empty or deaths is None or deaths.empty:
            return [], smoke_events
        start_tick = demo.regular_rounds[0].start_tick if demo.regular_rounds else 0
        # live smoke windows: detonate -> expired (entityid match) or default 18s
        spans: list[tuple[int, int, float, float]] = []
        end_by_entity: dict[int, int] = {}
        if expired is not None and not expired.empty:
            for _, row in expired.iterrows():
                eid = row.get("entityid")
                if eid is not None and str(eid) != "nan":
                    try:
                        end_by_entity[int(eid)] = int(row.get("tick", 0) or 0)
                    except (ValueError, TypeError):
                        continue
        for _, row in det.iterrows():
            t0 = int(row.get("tick", 0) or 0)
            if t0 < start_tick:
                continue
            # demoparser2 0.42 emits lowercase x/y (grenade landing point);
            # accept uppercase too so synthetic/legacy frames keep working.
            x = _xy(row, "x", "X")
            y = _xy(row, "y", "Y")
            if x is None or y is None:
                continue
            eid = row.get("entityid")
            t1 = end_by_entity.get(int(eid)) if eid is not None and str(eid) != "nan" else None
            if t1 is None or t1 <= t0:
                t1 = t0 + int(18 * 64)
            spans.append((t0, t1, x, y))
            thrower = clean_sid(row.get("user_steamid", ""))
            rnd = demo.data.round_at_tick(t0)
            smoke_events.append({
                "x": x, "y": y, "round": rnd.number if rnd else 0,
                "side": side_at(thrower, t0) if thrower else "",
                "kind": "smoke",
            })

        def in_smoke(tick: int, x: float, y: float) -> bool:
            for t0, t1, sx, sy in spans:
                if t0 <= tick <= t1 and math.hypot(x - sx, y - sy) <= SMOKE_RADIUS:
                    return True
            return False

        counters: dict[str, dict] = {}
        for _, row in deaths.iterrows():
            t = int(row.get("tick", 0) or 0)
            if t < start_tick:
                continue
            vx, vy = _finite(row.get("user_X")), _finite(row.get("user_Y"))
            kx, ky = _finite(row.get("attacker_X")), _finite(row.get("attacker_Y"))
            if vx is None or kx is None:
                continue
            vic_in = in_smoke(t, vx, vy)
            att_in = in_smoke(t, kx, ky)
            if not (vic_in or att_in):
                continue
            att = clean_sid(row.get("attacker_steamid", ""))
            vic = clean_sid(row.get("user_steamid", ""))
            if att and att != vic:
                s = counters.setdefault(att, {"smoke_kills": 0, "smoke_deaths": 0,
                                              "name": str(row.get("attacker_name", "") or att)})
                if vic_in and not att_in:
                    s["smoke_kills"] += 1
                    rnd = demo.data.round_at_tick(t)
                    smoke_events.append({
                        "x": vx, "y": vy, "round": rnd.number if rnd else 0,
                        "side": side_at(vic, t), "kind": "kill",
                    })
            if vic:
                s = counters.setdefault(vic, {"smoke_kills": 0, "smoke_deaths": 0,
                                              "name": str(row.get("user_name", "") or vic)})
                if vic_in and not att_in:
                    s["smoke_deaths"] += 1
        out = []
        for sid, s in counters.items():
            if s["smoke_kills"] or s["smoke_deaths"]:
                out.append({
                    "steamid": sid, "name": s["name"] or sid,
                    "smoke_kills": s["smoke_kills"], "smoke_deaths": s["smoke_deaths"],
                    "side": side_at(sid, None) or "",
                })
        out.sort(key=lambda x: -(x["smoke_kills"] * 2 - x["smoke_deaths"]))
        return out, smoke_events

    def _player_sides(self, demo: ParsedDemo) -> dict[str, str]:
        """Deprecated whole-demo side map (Phase I): kept only for API compat.
        Callers now use the tick-resolved `side_at` closure built in run()."""
        sides: dict[str, str] = {}
        round_sides = round_player_sides(demo)
        tally: dict[str, dict[str, int]] = {}
        for m in round_sides.values():
            for sid, s in m.items():
                tally.setdefault(sid, {}).setdefault(s, 0)
                tally[sid][s] += 1
        for sid, counts in tally.items():
            sides[sid] = max(counts.items(), key=lambda kv: kv[1])[0]
        return sides

    # ---- R4 道具执行科学 ----
    def _execute_science(self, demo: ParsedDemo, side_at) -> tuple[list[dict], list[dict]]:
        """Support flashes / late utility / molly damage / smoke-vs-win buckets.

        Execute anchor per round = min(first player_hurt, bomb_planted) —
        the moment the round "became real". Utility detonating >5s after the
        anchor is "late". A support flash = a detonation that blinded ≥1
        enemy AND a same-side TEAMMATE (not the thrower) killed one of the
        blinded enemies within 3s.
        """
        events = demo.events
        rounds = demo.regular_rounds
        if not rounds:
            return [], []
        start = rounds[0].start_tick

        hurt = events.get("player_hurt")
        # execute anchor per round
        anchor: dict[int, int] = {}
        if hurt is not None and not hurt.empty:
            for _, row in hurt.iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start:
                    continue
                rnd = demo.data.round_at_tick(t)
                if rnd is None:
                    continue
                if rnd.number not in anchor or t < anchor[rnd.number]:
                    anchor[rnd.number] = t
        planted = events.get("bomb_planted")
        if planted is not None and not planted.empty:
            for _, row in planted.iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start:
                    continue
                rnd = demo.data.round_at_tick(t)
                if rnd is None:
                    continue
                if rnd.number not in anchor or t < anchor[rnd.number]:
                    anchor[rnd.number] = t

        # blind index for the support-flash scan (tick, victim)
        blind = events.get("player_blind")
        blind_rows: list[tuple[int, str]] = []
        if blind is not None and not blind.empty:
            for _, row in blind.iterrows():
                vic = clean_sid(row.get("user_steamid", ""))
                t = int(row.get("tick", 0) or 0)
                if vic and t >= start and (_finite(row.get("blind_duration")) or 0) > 0:
                    blind_rows.append((t, vic))
        blind_rows.sort()

        # kills index: (tick, attacker, victim, side_of_attacker)
        kills: list[tuple[int, str, str, str]] = []
        deaths = events.get("player_death")
        if deaths is not None and not deaths.empty:
            for _, row in deaths.iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start:
                    continue
                att = clean_sid(row.get("attacker_steamid", ""))
                vic = clean_sid(row.get("user_steamid", ""))
                if att and vic and att != vic:
                    kills.append((t, att, vic, side_at(att, t)))
        kills.sort()

        import bisect

        stats: dict[str, dict] = {}

        def S(sid: str, name: str = "") -> dict:
            return stats.setdefault(sid, {
                "steamid": sid, "name": name or sid,
                "enemy_blind_throws": 0, "support_kills": 0, "own_followups": 0,
                "throws": 0, "late_throws": 0,
                "molly_throws": 0, "inc_throws": 0, "molly_dmg": 0,
            })

        # per-thrower grenade detonations (throws) + late accounting.
        # Molotov vs incendiary: molotov_detonate marks molotov throws;
        # inferno_startburn marks incendiary throws — but some broadcasts fire
        # BOTH for one molotov, so inferno counts stay separate and are only
        # used as a fallback when the demo has zero molotov_detonate.
        throw_sources = (
            ("flashbang_detonate", False),
            ("smokegrenade_detonate", False),
            ("hegrenade_detonate", False),
            ("molotov_detonate", "molly"),
            ("inferno_startburn", "inc"),
        )
        for evt, molly_kind in throw_sources:
            table = events.get(evt)
            if table is None or table.empty:
                continue
            for _, row in table.iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start:
                    continue
                thrower = clean_sid(row.get("user_steamid", ""))
                if not thrower:
                    continue
                s = S(thrower, str(row.get("user_name", "") or ""))
                s["throws"] += 1
                if molly_kind == "molly":
                    s["molly_throws"] += 1
                elif molly_kind == "inc":
                    s["inc_throws"] += 1
                rnd = demo.data.round_at_tick(t)
                a = anchor.get(rnd.number) if rnd else None
                if a is not None and t > a + LATE_AFTER_TICKS:
                    s["late_throws"] += 1
        total_molly = sum(s["molly_throws"] for s in stats.values())
        if total_molly == 0:  # fallback: inferno_startburn as the molly marker
            for s in stats.values():
                s["molly_throws"] = s.get("inc_throws", 0)

        # support flashes: per flash detonation blinding enemies
        flash_det = events.get("flashbang_detonate")
        if flash_det is not None and not flash_det.empty:
            bticks = [b[0] for b in blind_rows]
            for _, row in flash_det.iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start:
                    continue
                thrower = clean_sid(row.get("user_steamid", ""))
                if not thrower:
                    continue
                thrower_side = side_at(thrower, t)
                if not thrower_side:
                    continue
                blinded: list[str] = []
                for i in range(bisect.bisect_left(bticks, t - FLASH_WINDOW_TICKS), len(blind_rows)):
                    bt, vic = blind_rows[i]
                    if bt > t + FLASH_WINDOW_TICKS:
                        break
                    if vic == thrower:
                        continue
                    if side_at(vic, bt) and side_at(vic, bt) != thrower_side:
                        blinded.append(vic)
                if not blinded:
                    continue
                s = S(thrower, str(row.get("user_name", "") or ""))
                s["enemy_blind_throws"] += 1
                blinded_set = set(blinded)
                for kt, att, vic, att_side in kills:
                    if kt > t + EXEC_SUPPORT_WINDOW_TICKS:
                        break
                    if kt < t or vic not in blinded_set:
                        continue
                    if att_side != thrower_side:
                        continue
                    if att == thrower:
                        s["own_followups"] += 1
                    else:
                        s["support_kills"] += 1

        # molly damage credit (player_hurt weapon in _MOLLY_KEYS)
        if hurt is not None and not hurt.empty:
            for _, row in hurt.iterrows():
                wpn = str(row.get("weapon", "") or "").lower()
                if not any(k in wpn for k in _MOLLY_KEYS):
                    continue
                att = clean_sid(row.get("attacker_steamid", ""))
                if not att:
                    continue
                s = S(att, str(row.get("attacker_name", "") or ""))
                s["molly_dmg"] += int(row.get("dmg_health", 0) or 0)

        out = []
        for s in stats.values():
            n_bl = s["enemy_blind_throws"]
            s["support_flash_rate"] = round(s["support_kills"] / n_bl, 3) if n_bl else None
            s["late_rate"] = round(s["late_throws"] / s["throws"], 3) if s["throws"] else None
            s["molly_dmg_per_throw"] = (round(s["molly_dmg"] / s["molly_throws"], 1)
                                        if s["molly_throws"] else None)
            out.append(s)
        out.sort(key=lambda x: (-x["support_kills"], -x["enemy_blind_throws"]))

        # smoke-before-contact buckets per attacking side per round
        det = events.get("smokegrenade_detonate")
        smokes_before: dict[int, dict[str, int]] = {}
        if det is not None and not det.empty:
            for _, row in det.iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start:
                    continue
                rnd = demo.data.round_at_tick(t)
                if rnd is None:
                    continue
                a = anchor.get(rnd.number)
                if a is None or t > a:  # only count smokes BEFORE first contact
                    continue
                thrower = clean_sid(row.get("user_steamid", ""))
                sde = side_at(thrower, t) if thrower else ""
                if sde:
                    smokes_before.setdefault(rnd.number, {})[sde] = \
                        smokes_before.setdefault(rnd.number, {}).get(sde, 0) + 1
        exec_rounds = []
        for rnd in rounds:
            if rnd.number not in anchor or not rnd.winner_side:
                continue
            for side in ("T", "CT"):
                n = smokes_before.get(rnd.number, {}).get(side, 0)
                exec_rounds.append({
                    "round": rnd.number, "side": side,
                    "smokes": min(n, 2),  # 0/1/2+ buckets
                    "won": 1 if rnd.winner_side == side else 0,
                })
        return out, exec_rounds

