"""Post-plant analytics (下包后分析, Phase I F6).

For every round containing a bomb plant:
  - hold: did T win after planting? retake: did CT win it back?
  - defuse attempts from bomb_begindefuse (haskit) / bomb_abortdefuse —
    probed available on WMPVP broadcasts; when the tables are absent the
    attempt count falls back to completed defuses (documented approximation)
  - time-to-defuse distribution

bomb_planted carries a direct `site` column on real demos; falls back to
user_last_place_name inference for older caches.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)


class PostPlantResult(AnalysisResult):
    # per planted round: {round, site, winner_side, plant_tick, defused,
    #                    defuse_tick, time_to_defuse_s, defuse_attempts}
    rounds: list[dict] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


@register_module
class PostPlantModule(AnalysisModule):
    name = "postplant"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        res = PostPlantResult(module=self.name, demo_hash=demo.metadata.demo_hash)
        plants = demo.events.get("bomb_planted")
        if plants is None or plants.empty:
            return res
        defused = demo.events.get("bomb_defused")
        begins = demo.events.get("bomb_begindefuse")
        aborts = demo.events.get("bomb_abortdefuse")

        out: list[dict] = []
        for _, row in plants.iterrows():
            plant_tick = int(row.get("tick", 0) or 0)
            rnd = demo.data.round_at_tick(plant_tick)
            if rnd is None or rnd.is_warmup:
                continue
            site = str(row.get("site", "") or "").strip().upper()
            if site not in ("A", "B"):
                # real demoparser2 demos carry numeric place ids here (313/376…)
                # — the planter's last place name ("BombsiteA") is the reliable
                # A/B signal; keep the raw code only as a last resort.
                place = str(row.get("user_last_place_name", "") or "").upper()
                site = "A" if "A" in place else "B" if "B" in place else site

            defuse_tick = None
            if defused is not None and not defused.empty:
                in_r = defused[(defused["tick"] >= rnd.start_tick) & (defused["tick"] <= rnd.end_tick)]
                if not in_r.empty:
                    defuse_tick = int(in_r["tick"].iloc[0])

            attempts = 0
            if begins is not None and not begins.empty:
                in_b = begins[(begins["tick"] >= plant_tick)
                              & (begins["tick"] <= rnd.end_tick)]
                attempts += len(in_b)
            elif defuse_tick is not None:
                attempts = 1  # documented fallback: count completions only

            ttd = ((defuse_tick - plant_tick) / 64.0) if defuse_tick else None
            out.append({
                "round": rnd.number,
                "site": site,
                "winner_side": rnd.winner_side,
                "plant_tick": plant_tick,
                "defused": defuse_tick is not None,
                "time_to_defuse_s": round(ttd, 2) if ttd is not None else None,
                "defuse_attempts": attempts,
                "t_score": rnd.t_score,
                "ct_score": rnd.ct_score,
            })

        planted_n = len(out)
        t_holds = sum(1 for r in out if r["winner_side"] == "T")
        ct_retales = sum(1 for r in out if r["winner_side"] == "CT")
        defusals = sum(1 for r in out if r["defused"])
        aborted = 0
        if aborts is not None and not aborts.empty:
            aborted = len(aborts[aborts["tick"] >= (demo.regular_rounds[0].start_tick
                                                    if demo.regular_rounds else 0)])
        res.rounds = sorted(out, key=lambda r: r["round"])
        res.summary = {
            "planted_rounds": planted_n,
            "t_hold_rate": round(t_holds / planted_n, 3) if planted_n else None,
            "ct_retake_rate": round(ct_retales / planted_n, 3) if planted_n else None,
            "defusal_count": defusals,
            "defusal_rate": round(defusals / planted_n, 3) if planted_n else None,
            "defuse_attempts": sum(r["defuse_attempts"] for r in out),
            "defuse_aborts": aborted,
            "avg_time_to_defuse_s": (
                round(sum(r["time_to_defuse_s"] for r in out if r["time_to_defuse_s"] is not None)
                      / max(defusals, 1), 2)
                if defusals else None
            ),
        }
        return res
