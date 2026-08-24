"""Utility effectiveness (道具效用评估, Phase F M8).

Flash value: per flashbang_detonate by player P, sum the blind_duration of
ENEMIES blinded within a ±window; friendly blinds count at half value.
Smoke denial: kills where the victim stood inside a live smoke zone while the
killer was outside it (烟中击杀).
"""
from __future__ import annotations

import logging
import math

from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.replay.timeline import round_freeze_ends

logger = logging.getLogger(__name__)

FLASH_WINDOW_TICKS = 96   # ±1.5s at 64 tick
SMOKE_RADIUS = 120        # world units
FRIENDLY_BLIND_WEIGHT = 0.5


def _finite(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class UtilityEffectResult(AnalysisResult):
    # per thrower: flash stats
    flashers: list[dict] = Field(default_factory=list)
    # smoke denial counters per player
    smoke: list[dict] = Field(default_factory=list)


@register_module
class UtilityEffectModule(AnalysisModule):
    name = "utility_effect"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        side_at = self._player_sides(demo)
        flashers = self._flash_value(demo, side_at)
        smoke = self._smoke_denial(demo, side_at)
        return UtilityEffectResult(
            module=self.name, demo_hash=demo.metadata.demo_hash,
            flashers=flashers, smoke=smoke,
        )

    # ---- flash value ----
    def _flash_value(self, demo: ParsedDemo, side_at: dict[str, str]) -> list[dict]:
        det = demo.events.get("flashbang_detonate")
        blind = demo.events.get("player_blind")
        if det is None or det is None or blind is None or blind.empty:
            return []
        start_tick = demo.regular_rounds[0].start_tick if demo.regular_rounds else 0
        # index blind rows by tick for windowed scans
        blind_rows = []
        for _, row in blind.iterrows():
            t = int(row.get("tick", 0) or 0)
            vic = str(row.get("user_steamid", "") or "")
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
            thrower = str(row.get("user_steamid", "") or "")
            if not thrower:
                continue
            s = stats.setdefault(thrower, {"throws": 0, "enemy_blind_s": 0.0,
                                           "friendly_blind_s": 0.0, "name": ""})
            s["throws"] += 1
            name = str(row.get("user_name", "") or "")
            if name:
                s["name"] = name
            thrower_side = side_at.get(thrower)
            lo = t - FLASH_WINDOW_TICKS
            import bisect
            for i in range(bisect.bisect_left(bticks, lo), len(blind_rows)):
                bt, vic, dur = blind_rows[i]
                if bt > t + FLASH_WINDOW_TICKS:
                    break
                if vic == thrower:
                    continue  # self-blind doesn't count against the throw
                if side_at.get(vic) == thrower_side:
                    s["friendly_blind_s"] += dur
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
                "side": side_at.get(sid, ""),
            })
        out.sort(key=lambda x: -x["value"])
        return out

    # ---- smoke denial ----
    def _smoke_denial(self, demo: ParsedDemo, side_at: dict[str, str]) -> list[dict]:
        det = demo.events.get("smokegrenade_detonate")
        expired = demo.events.get("smokegrenade_expired")
        deaths = demo.events.get("player_death")
        if det is None or det.empty or deaths is None or deaths.empty:
            return []
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
            x = _finite(row.get("X"))
            y = _finite(row.get("Y"))
            if x is None or y is None:
                continue
            eid = row.get("entityid")
            t1 = end_by_entity.get(int(eid)) if eid is not None and str(eid) != "nan" else None
            if t1 is None or t1 <= t0:
                t1 = t0 + int(18 * 64)
            spans.append((t0, t1, x, y))

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
            att = str(row.get("attacker_steamid", "") or "")
            vic = str(row.get("user_steamid", "") or "")
            if att and att != vic:
                s = counters.setdefault(att, {"smoke_kills": 0, "smoke_deaths": 0,
                                              "name": str(row.get("attacker_name", "") or att)})
                if vic_in and not att_in:
                    s["smoke_kills"] += 1
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
                    "side": side_at.get(sid, ""),
                })
        out.sort(key=lambda x: -(x["smoke_kills"] * 2 - x["smoke_deaths"]))
        return out

    def _player_sides(self, demo: ParsedDemo) -> dict[str, str]:
        sides: dict[str, str] = {}
        ticks = demo.ticks
        if ticks is None or ticks.empty or not {"steamid", "team_num"} <= set(ticks.columns):
            return sides
        grouped = ticks.groupby("steamid")["team_num"]
        for sid, codes in grouped:
            codes = codes.dropna()
            if codes.empty:
                continue
            mean = float(codes.mean())
            sides[str(sid)] = "T" if mean < 2.5 else "CT"
        return sides
