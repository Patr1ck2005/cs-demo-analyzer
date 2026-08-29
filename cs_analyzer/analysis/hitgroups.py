"""Hitgroup damage (部位伤害分布, Phase I F2).

player_hurt.hitgroup x dmg_health per attacker — where your damage lands.
Also computes armor efficiency: share of raw damage the armor absorbed
(dmg_armor / (dmg_health + dmg_armor)) over armor-relevant hits.

hitgroup values are strings on real demos (verified 2026-08-25):
head/neck/chest/stomach/left_arm/right_arm/left_leg/right_leg/generic.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.basic_stats import BasicStatsModule
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

# canonical groups for the stacked-bar chart; arm variants fold into "arm"
GROUPS = ("head", "chest", "stomach", "arm", "leg", "generic")
_FOLD = {
    "head": "head", "neck": "head",  # neck hits behave like head (armor-ignoring)
    "chest": "chest",
    "stomach": "stomach",
    "left_arm": "arm", "right_arm": "arm",
    "left_leg": "leg", "right_leg": "leg",
    "generic": "generic",  # grenades/fire/world
}
ZH_LABELS = {"head": "头/颈", "chest": "胸", "stomach": "腹", "arm": "手臂",
             "leg": "腿", "generic": "范围(爆炸/火)"}


class HitgroupsResult(AnalysisResult):
    players: list[dict] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=lambda: list(GROUPS))
    labels: dict[str, str] = Field(default_factory=lambda: dict(ZH_LABELS))


@register_module
class HitgroupsModule(AnalysisModule):
    name = "hitgroups"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        res = HitgroupsResult(module=self.name, demo_hash=demo.metadata.demo_hash)
        hurts = demo.events.get("player_hurt")
        if hurts is None or hurts.empty:
            return res
        rounds = demo.regular_rounds
        start_tick = rounds[0].start_tick if rounds else 0

        hurts = BasicStatsModule._filter_warmup(hurts)
        hurts = BasicStatsModule._exclude_teamkills(hurts)

        def _num(v) -> float:
            try:
                f = float(v)
                return f if f == f else 0.0
            except (TypeError, ValueError):
                return 0.0

        players: dict[str, dict] = {}
        for _, row in hurts.iterrows():
            tick = int(row.get("tick", 0) or 0)
            if tick < start_tick:
                continue
            att = str(row.get("attacker_steamid", "") or "")
            if not att:
                continue
            dmg = max(_num(row.get("dmg_health")), 0.0)
            armor_dmg = max(_num(row.get("dmg_armor")), 0.0)
            hg_raw = str(row.get("hitgroup", "") or "").strip().lower()
            hg = _FOLD.get(hg_raw, "generic")

            p = players.setdefault(att, {
                "name": str(row.get("attacker_name", "") or att),
                "damage": {g: 0.0 for g in GROUPS},
                "hits": {g: 0 for g in GROUPS},
                "_armor_absorbed": 0.0,
                "_armor_total": 0.0,
            })
            p["damage"][hg] += dmg
            p["hits"][hg] += 1
            # armor efficiency counts only hits where armor actually
            # interacted (dmg_armor > 0): zero-interaction hits (no helmet /
            # nade splash) carry no signal about penetration
            if hg != "generic" and armor_dmg > 0:
                p["_armor_absorbed"] += armor_dmg
                p["_armor_total"] += dmg + armor_dmg

        out = []
        for sid, p in players.items():
            out.append({
                "steamid": sid,
                "name": p["name"],
                "damage": {g: round(v, 1) for g, v in p["damage"].items()},
                "hits": dict(p["hits"]),
                "armor_efficiency": (
                    round(p["_armor_absorbed"] / p["_armor_total"], 3)
                    if p["_armor_total"] > 0 else None
                ),
            })
        out.sort(key=lambda x: -sum(x["damage"].values()))
        res.players = out
        return res
