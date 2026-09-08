"""Kill context (击杀情境, Phase I F1+F5): HOW each kill happened.

One warmup+teamkill-filtered walk of player_death reading the rich flag
columns that were parsed all along but never consumed:
  penetrated (穿墙), thrusmoke (烟中), noscope (盲狙), attackerinair (空中),
  headshot, distance (world units)
Plus two orphan tables finally read: round_mvp (MVP counts by reason) and
item_pickup (pickup profile via weapon categories).
Also ships a per-kill feed with badge flags for the kills tab, and a
canonical weapon mix for the distribution donut.
"""
from __future__ import annotations

import logging

from pydantic import Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.basic_stats import BasicStatsModule
from cs_analyzer.analysis.util import clean_sid
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.analysis.weapons import canonical, category

logger = logging.getLogger(__name__)

# distance buckets in world units for avg/max stats (no bucketing client-side)
_KNIFE_RANGE = 160  # beyond this a "knife" kill is suspicious but still counted


class KillContextResult(AnalysisResult):
    players: list[dict] = Field(default_factory=list)
    # [{tick, round, attacker, victim, weapon, badges:{...}}] chronological
    feed: list[dict] = Field(default_factory=list)
    # canonical weapon key -> kill count (distribution donut)
    weapon_mix: dict[str, int] = Field(default_factory=dict)


@register_module
class KillContextModule(AnalysisModule):
    name = "kill_context"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        res = KillContextResult(module=self.name, demo_hash=demo.metadata.demo_hash)

        deaths = demo.events.get("player_death")
        rounds = demo.regular_rounds
        start_tick = rounds[0].start_tick if rounds else 0

        players: dict[str, dict] = {}
        feed: list[dict] = []
        mix: dict[str, int] = {}

        if deaths is not None and not deaths.empty:
            deaths = BasicStatsModule._filter_warmup(deaths)
            deaths = BasicStatsModule._exclude_teamkills(deaths)
            for _, row in deaths.iterrows():
                tick = int(row.get("tick", 0) or 0)
                if tick < start_tick:
                    continue
                att = clean_sid(row.get("attacker_steamid", ""))
                vic = clean_sid(row.get("user_steamid", ""))
                if not att or att == vic:
                    continue
                weapon_raw = str(row.get("weapon", "") or "")
                dist = row.get("distance")
                try:
                    dist_v = float(dist) if dist is not None and str(dist) != "nan" else None
                except (TypeError, ValueError):
                    dist_v = None
                badges = {
                    "penetrated": bool(row.get("penetrated", False)),
                    "thrusmoke": bool(row.get("thrusmoke", False)),
                    "noscope": bool(row.get("noscope", False)),
                    "airborne": bool(row.get("attackerinair", False)),
                    "headshot": bool(row.get("headshot", False)),
                    "distance": round(dist_v, 1) if dist_v is not None else None,
                }
                p = players.setdefault(att, self._blank(str(row.get("attacker_name", "") or att)))
                p["kills"] += 1
                if badges["penetrated"]:
                    p["penetrated_kills"] += 1
                if badges["thrusmoke"]:
                    p["thrusmoke_kills"] += 1
                if badges["noscope"]:
                    p["noscope_kills"] += 1
                if badges["airborne"]:
                    p["airborne_kills"] += 1
                if badges["distance"] is not None:
                    p["_dist_sum"] += badges["distance"]
                    p["_dist_n"] += 1
                    p["max_distance"] = max(p["max_distance"], badges["distance"])

                canon = canonical(weapon_raw)
                mix[canon] = mix.get(canon, 0) + 1

                rnd = demo.data.round_at_tick(tick)
                feed.append({
                    "tick": tick,
                    "round": rnd.number if rnd else None,
                    "attacker": att,
                    "victim": vic,
                    "attacker_name": str(row.get("attacker_name", "") or ""),
                    "victim_name": str(row.get("user_name", "") or ""),
                    "weapon": canon,
                    "badges": badges,
                })

        # F5a: MVP table (parsed since day one, never read)
        mvp = demo.events.get("round_mvp")
        if mvp is not None and not mvp.empty:
            for _, row in mvp.iterrows():
                sid = clean_sid(row.get("user_steamid", ""))
                if not sid:
                    continue
                p = players.setdefault(sid, self._blank(str(row.get("user_name", "") or sid)))
                reason = str(row.get("reason", "") or "")
                p["mvp_counts"][reason] = p["mvp_counts"].get(reason, 0) + 1
                p["mvp_total"] += 1

        # F5b: pickup profile via canonical categories
        pickups = demo.events.get("item_pickup")
        cat_of = {c: c for c in ("kevlar", "kevlarhelmet", "defuser")}
        if pickups is not None and not pickups.empty:
            for _, row in pickups.iterrows():
                sid = clean_sid(row.get("user_steamid", ""))
                if not sid:
                    continue
                item_raw = str(row.get("item", "") or "")
                canon = canonical(item_raw)
                cat = category(item_raw)
                key = cat_of.get(canon, cat)  # gear keeps its own keys
                p = players.setdefault(sid, self._blank(""))
                p["pickups"][key] = p["pickups"].get(key, 0) + 1

        out = []
        for sid, p in players.items():
            out.append({
                "steamid": sid,
                "name": p["name"],
                "kills": p["kills"],
                "penetrated_kills": p["penetrated_kills"],
                "thrusmoke_kills": p["thrusmoke_kills"],
                "noscope_kills": p["noscope_kills"],
                "airborne_kills": p["airborne_kills"],
                "avg_distance": round(p["_dist_sum"] / p["_dist_n"], 1) if p["_dist_n"] else None,
                "max_distance": p["max_distance"] if p["max_distance"] else None,
                "mvp_total": p["mvp_total"],
                "mvp_counts": p["mvp_counts"],
                "pickups": p["pickups"],
            })
        out.sort(key=lambda x: -x["kills"])
        res.players = out
        feed.sort(key=lambda f: f["tick"])
        res.feed = feed
        res.weapon_mix = dict(sorted(mix.items(), key=lambda kv: -kv[1]))
        return res

    @staticmethod
    def _blank(name: str) -> dict:
        return {
            "name": name, "kills": 0,
            "penetrated_kills": 0, "thrusmoke_kills": 0,
            "noscope_kills": 0, "airborne_kills": 0,
            "_dist_sum": 0.0, "_dist_n": 0, "max_distance": 0.0,
            "mvp_total": 0, "mvp_counts": {}, "pickups": {},
        }
