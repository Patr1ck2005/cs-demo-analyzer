"""Weapon-dimension splits (武器维度拆分, Phase I F7).

player_death.weapon canonicalized through web.weapons (skin variants
collapse: ak47_txz03 -> ak47): kills/deaths per category
(rifle/sniper/pistol/smg/heavy/knife/grenade/world) + each player's top-3
exact weapons.
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


class WeaponSplitsResult(AnalysisResult):
    players: list[dict] = Field(default_factory=list)


@register_module
class WeaponSplitsModule(AnalysisModule):
    name = "weapon_splits"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        res = WeaponSplitsResult(module=self.name, demo_hash=demo.metadata.demo_hash)
        deaths = demo.events.get("player_death")
        if deaths is None or deaths.empty:
            return res
        rounds = demo.regular_rounds
        start_tick = rounds[0].start_tick if rounds else 0

        deaths = BasicStatsModule._filter_warmup(deaths)
        deaths = BasicStatsModule._exclude_teamkills(deaths)

        players: dict[str, dict] = {}
        for _, row in deaths.iterrows():
            tick = int(row.get("tick", 0) or 0)
            if tick < start_tick:
                continue
            weapon_raw = str(row.get("weapon", "") or "")
            canon = canonical(weapon_raw)
            cat = category(weapon_raw)

            att = clean_sid(row.get("attacker_steamid", ""))
            vic = clean_sid(row.get("user_steamid", ""))
            # §7.8: NaN steamid (world/C4 kills with no attacker) must not
            # invent a fake "nan" player row (visual audit M5 finding)
            if att.lower() == "nan":
                att = ""
            if vic.lower() == "nan":
                vic = ""

            if att and att != vic:
                p = players.setdefault(att, self._blank(str(row.get("attacker_name", "") or att)))
                p["kills_by_category"][cat] = p["kills_by_category"].get(cat, 0) + 1
                p["_exact"][canon] = p["_exact"].get(canon, 0) + 1
            if vic:
                p = players.setdefault(vic, self._blank(str(row.get("user_name", "") or vic)))
                p["deaths_by_category"][cat] = p["deaths_by_category"].get(cat, 0) + 1

        out = []
        for sid, p in players.items():
            exact = sorted(p["_exact"].items(), key=lambda kv: -kv[1])[:3]
            out.append({
                "steamid": sid,
                "name": p["name"],
                "kills_by_category": p["kills_by_category"],
                "deaths_by_category": p["deaths_by_category"],
                "top_weapons": [{"weapon": w, "kills": n} for w, n in exact],
            })
        out.sort(key=lambda x: -sum(x["kills_by_category"].values()))
        res.players = out
        return res

    @staticmethod
    def _blank(name: str) -> dict:
        return {"name": name, "kills_by_category": {}, "deaths_by_category": {}, "_exact": {}}
