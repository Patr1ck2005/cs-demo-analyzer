"""Duel matrix (对枪矩阵, Phase F M7): pairwise attacker-vs-victim outcomes.

From player_death: kills[a][b] counts how many times a killed b; the win rate
of the pairing is k/(k+d) with d = kills[b][a]. Cells under MIN_DUELS are
greyed client-side (sample too small to mean anything).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid, round_player_sides
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

MIN_DUELS = 3  # cells with fewer engagements are statistically noise


class DuelMatrixResult(AnalysisResult):
    players: list[str] = Field(default_factory=list)  # steamids, matrix order
    names: dict[str, str] = Field(default_factory=dict)
    sides: dict[str, str] = Field(default_factory=dict)  # steamid -> "T"/"CT"
    # kills[i][j] = players[i] killed players[j]
    kills: dict[str, dict[str, int]] = Field(default_factory=dict)
    min_duels: int = MIN_DUELS

    def total_kills(self) -> int:
        return sum(v for row in self.kills.values() for v in row.values())


@register_module
class DuelsModule(AnalysisModule):
    name = "duels"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        df = demo.events.get("player_death")
        kills: dict[str, dict[str, int]] = {}
        names: dict[str, str] = {}
        sides: dict[str, str] = {}
        if df is not None and not df.empty:
            # warmup filter: drop kills before the first regular round starts
            start_tick = demo.regular_rounds[0].start_tick if demo.regular_rounds else 0
            for _, row in df.iterrows():
                if int(row.get("tick", 0) or 0) < start_tick:
                    continue
                att = clean_sid(row.get("attacker_steamid", ""))
                vic = clean_sid(row.get("user_steamid", ""))
                # §7.8: NaN steamid str()s to "nan" — a fake duelist (M5 audit)
                if att.lower() == "nan":
                    att = ""
                if vic.lower() == "nan":
                    vic = ""
                if not att or not vic or att == vic:
                    continue  # suicides/world deaths don't count as duels
                kills.setdefault(att, {}).setdefault(vic, 0)
                kills[att][vic] += 1
                names.setdefault(att, str(row.get("attacker_name", "") or att))
                names.setdefault(vic, str(row.get("user_name", "") or vic))

        players = sorted(kills.keys())
        # side per player: majority of per-round sides (swap-safe — the old
        # whole-demo team_num mean mislabeled everyone after halftime)
        round_sides = round_player_sides(demo)
        if round_sides:
            tally: dict[str, dict[str, int]] = {}
            for m in round_sides.values():
                for sid, s in m.items():
                    tally.setdefault(sid, {}).setdefault(s, 0)
                    tally[sid][s] += 1
            for sid in players:
                counts = tally.get(sid)
                if counts:
                    sides[sid] = max(counts.items(), key=lambda kv: kv[1])[0]

        return DuelMatrixResult(
            module=self.name, demo_hash=demo.metadata.demo_hash,
            players=players, names=names, sides=sides, kills=kills,
        )
