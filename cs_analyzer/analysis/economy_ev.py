"""Economy decision EV (Phase V2 决策 EV 面板).

Answers "在这个经济局面买什么更值" with an EV query table built from the
whole library: decision-state (buy type, round-half score differential,
consecutive-loss streak) → observed round win rate + survival rate.

Statistical discipline (user-approved M-line rules): every cell shows its
real sample size N; cells under MIN_SAMPLES render grey/None so a 1-game
100% can never mislead (the "6.7% (1局0胜)" lesson).

Pure aggregation — reuses EconomyModule's TeamRoundBuy rows and the deaths
event for survival, no per-tick work.
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid
from cs_analyzer.model.parsed_demo import ParsedDemo

MIN_SAMPLES = 5  # cells below N=5 are None (grey in UI)
BUYS = ("eco", "force", "full")


class EVCell(BaseModel):
    buy: str
    side: str
    score_bin: str   # "losing" | "even" | "winning"
    streak_bin: str  # "cold" (streak>=2) | "warm" (<2)
    n: int
    wins: int
    win_rate: float | None = None
    survived: float | None = None  # 回合末存活率均值：该方存活人数/该方人数 的回合均值


class EconomyEVResult(AnalysisResult):
    cells: list[EVCell] = Field(default_factory=list)
    min_samples: int = MIN_SAMPLES
    total_rounds: int = 0


@register_module
class EconomyEVModule(AnalysisModule):
    name = "economy_ev"
    requires = ("economy",)

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        eco = ctx.require("economy")
        deaths = demo.events.get("player_death")
        rounds = demo.regular_rounds
        if not eco.rounds or not rounds:
            return EconomyEVResult(module=self.name, demo_hash=demo.metadata.demo_hash)

        deaths_by_round: dict[int, set[str]] = defaultdict(set)
        if deaths is not None and not deaths.empty:
            for row in deaths.itertuples(index=False):
                sid = clean_sid(row.user_steamid)
                if sid:
                    deaths_by_round[_round_of(int(row.tick), rounds)].add(sid)

        # side per player per round (round_player_sides, swap-safe)
        from cs_analyzer.analysis.util import round_player_sides

        sides = round_player_sides(demo)

        # per-side consecutive-loss streak BEFORE each round (chronological)
        streaks: dict[tuple[int, str], int] = {}
        cur: dict[str, int] = {"T": 0, "CT": 0}
        for r in sorted(rounds, key=lambda x: x.number):
            for side in ("T", "CT"):
                streaks[(r.number, side)] = cur[side]
            for side in ("T", "CT"):
                if getattr(r, "winner_side", "") == side:
                    cur[side] = 0
                elif cur.get(side, 0) is not None:
                    cur[side] = cur.get(side, 0) + 1

        # ---- aggregate cells ----
        # key: (buy, side, score_bin, streak_bin) -> [n, wins, survived_sum]
        agg: dict[tuple, list] = defaultdict(lambda: [0, 0, 0.0])
        total_rounds = 0
        team_rounds: dict[int, list] = defaultdict(list)
        for rb in eco.rounds:
            team_rounds[rb.round].append(rb)
        for rnd_num, rbs in team_rounds.items():
            rnd = next((r for r in rounds if r.number == rnd_num), None)
            if rnd is None:
                continue
            total_rounds += 1
            t_score, ct_score = rnd.t_score, rnd.ct_score
            for rb in rbs:
                if rb.won is None:
                    continue
                # score differential BEFORE the round resolves: use the round's
                # end score minus this round's contribution — approximate with
                # the live score at the round's midpoint (t_score/ct_score are
                # end-of-round; shift by this round's winner)
                my, opp = t_score, ct_score
                if rb.side == "CT":
                    my, opp = ct_score, t_score
                diff = my - opp
                if getattr(rnd, "winner_side", "") == rb.side:
                    diff -= 1
                else:
                    diff += 1
                score_bin = "losing" if diff < 0 else ("winning" if diff > 0 else "even")
                streak = streaks.get((rnd_num, rb.side), 0)
                streak_bin = "cold" if streak >= 2 else "warm"
                # survival: players of this side alive at round end
                alive_players = 0
                played = 0
                side_map = sides.get(rnd_num, {})
                for sid, side in side_map.items():
                    if side != rb.side:
                        continue
                    played += 1
                    if sid not in deaths_by_round.get(rnd_num, set()):
                        alive_players += 1
                key = (rb.buy, rb.side, score_bin, streak_bin)
                cell = agg[key]
                cell[0] += 1
                cell[1] += 1 if rb.won else 0
                if played:
                    cell[2] += alive_players / played

        cells = []
        for (buy, side, score_bin, streak_bin), (n, wins, surv) in sorted(agg.items()):
            cells.append(EVCell(
                buy=buy, side=side, score_bin=score_bin, streak_bin=streak_bin,
                n=n, wins=wins,
                win_rate=round(wins / n, 3) if n >= MIN_SAMPLES else None,
                survived=round(surv / n, 3) if n >= MIN_SAMPLES else None,
            ))

        return EconomyEVResult(
            module=self.name, demo_hash=demo.metadata.demo_hash,
            cells=cells, min_samples=MIN_SAMPLES, total_rounds=total_rounds,
        )


def _round_of(tick: int, rounds: list) -> int:
    for r in rounds:
        if r.start_tick <= tick <= r.end_tick:
            return r.number
    return rounds[0].number if rounds else 0
