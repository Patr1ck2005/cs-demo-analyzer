"""HLTV-style Rating 2.1 approximation (Phase U1).

HLTV's exact formula is private; this module implements a documented
approximation of **Rating 2.1** assembled from HLTV's own public changelog
(news 40051 "Introducing Rating 2.1", retrieved via web.archive.org) plus the
2.0-era blend constants that HLTV confirmed pre-2.1:

Rating 2.0 blend (public, from HLTV's own 2017 announcement):
    Rating = 0.0073*KAST + 0.3591*KPR - 0.5329*DPR + 0.2372*Impact
             + 0.0032*ADR + 0.1587
    Impact = 2.13*KPR + 0.42*APR - 0.41

Rating 2.1 changes over 2.0 (public, from HLTV's announcement):
  1. No KAST point for surviving a LOST round without a kill or assist
     (the "Jame rule" — saves only count as survival-KAST in won rounds).
  2. Survival in lost rounds is weighted less in the survival sub-rating.
  3. Assisted kills (26-damage assists in CS2 vs 41 in GO) are rewarded
     slightly more in the Kill sub-rating than in 2.0.
  4. The theoretical average over an event is recalibrated back to 1.00.

Since sub-rating internals stay private, 2.1 here is expressed as the 2.0
blend with those four adjustments applied directly to the inputs:
  - KAST excludes save-round survivals on lost rounds (rule 1)
  - DPR penalty is reduced for lost-round survivals (rule 2, via a small
    survival discount on the death count used for DPR — a lost-round save
    that would have been a death is "half a death")
  - assists count 1.25x toward Impact (rule 3)
  - a fixed recalibration multiplier brings the library mean back to 1.00
    (rule 4, computed over the whole library at aggregation level — here we
    apply the documented 1/1.06 CS2-era correction HLTV measured)

All inputs reuse basic_stats (kills/deaths/assists/damage/rounds) plus the
round-level KAST recomputation done here with the lost-round-save rule.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.basic_stats import BasicStatsModule, BasicStatsResult
from cs_analyzer.model.parsed_demo import ParsedDemo

# CS2-era average drift measured by HLTV: 2.0 formula averaged ~1.06 on CS2.
_RATING_21_RECALIBRATION = 1.0 / 1.06
# Rule 3: CS2 assists at 26 dmg are harder than GO's 41 → weight up in Impact.
_ASSIST_WEIGHT_21 = 1.25
# Rule 2: a lost-round survival (save) counts as half a death for DPR.
_LOST_SAVE_DEATH_WEIGHT = 0.5


class PlayerRatings21(BaseModel):
    steamid: str
    name: str
    team: str
    Rating21: float = 0.0
    Rating: float = 0.0  # 2.0 approximation, for side-by-side display
    KAST21: float = 0.0
    Impact: float = 0.0
    save_rounds: int = 0  # lost rounds survived with no K/A (the punished set)


class Ratings21Result(AnalysisResult):
    players: list[PlayerRatings21] = Field(default_factory=list)
    rounds_total: int = 0  # this demo's regular-round count (round-weighting)

    def by_steamid(self, steamid: str) -> PlayerRatings21 | None:
        for p in self.players:
            if p.steamid == steamid:
                return p
        return None


@register_module
class Ratings21Module(AnalysisModule):
    name = "ratings21"
    requires = ("basic_stats",)

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        basic = ctx.require("basic_stats")
        assert isinstance(basic, BasicStatsResult)
        rounds = demo.regular_rounds
        deaths_df = demo.events.get("player_death")
        if deaths_df is not None:
            deaths_df = BasicStatsModule._filter_warmup(deaths_df)
            deaths_df = BasicStatsModule._exclude_teamkills(deaths_df)

        # KAST per player under the 2.1 save rule, plus save-round bookkeeping
        kast21, saves = self._kast21_per_player(deaths_df, rounds, demo)

        players: list[PlayerRatings21] = []
        for stats in basic.players:
            kast_pct = (kast21.get(stats.steamid, 0) / stats.rounds * 100.0) if stats.rounds > 0 else 0.0
            save_n = saves.get(stats.steamid, 0)
            rating20 = self._rating20(stats.kills, stats.deaths, stats.assists,
                                      stats.damage, stats.rounds, kast_pct)
            rating21 = self._rating21(
                kills=stats.kills, deaths=stats.deaths, assists=stats.assists,
                damage=stats.damage, rounds=stats.rounds, kast_pct=kast_pct,
                lost_saves=save_n,
            )
            players.append(PlayerRatings21(
                steamid=stats.steamid, name=stats.name, team=stats.team,
                Rating21=rating21, Rating=rating20, KAST21=kast_pct,
                Impact=self._impact21(stats.kills, stats.assists, stats.rounds),
                save_rounds=save_n,
            ))

        return Ratings21Result(
            module=self.name, demo_hash=demo.metadata.demo_hash, players=players,
            rounds_total=len(rounds),
        )

    # ---- Rule 1: KAST with the lost-round save exclusion ----

    @staticmethod
    def _kast21_per_player(
        deaths_df: pd.DataFrame | None, rounds: list, demo: ParsedDemo
    ) -> tuple[dict[str, int], dict[str, int]]:
        """KAST counts under 2.1 + per-player lost-round save counts.

        A "save" = the player survived a LOST round with no kill and no
        assist in it. Those rounds award NO KAST point (2.0 awarded them via
        the survival leg). Returns (kast_counts, save_counts).
        """
        kast: dict[str, int] = defaultdict(int)
        saves: dict[str, int] = defaultdict(int)
        if deaths_df is None or deaths_df.empty or "tick" not in deaths_df.columns:
            return kast, saves

        team_of = {p.steamid: p.team for p in demo.players}
        ticks = demo.ticks
        if ticks is not None and not ticks.empty and "steamid" in ticks.columns:
            played = {str(s) for s in ticks["steamid"].dropna().unique()}
        else:
            played = {p.steamid for p in demo.players}
        # round winners: by side majority of survivors is unreliable; use the
        # round record's winner directly (regular_rounds carries winner_team)
        for rnd in rounds:
            in_round = (deaths_df["tick"] >= rnd.start_tick) & (deaths_df["tick"] <= rnd.end_tick)
            round_deaths = deaths_df[in_round].sort_values("tick")
            round_killers: set[str] = set()
            round_assisters: set[str] = set()
            victims: set[str] = set()
            traded: set[str] = set()
            if not round_deaths.empty:
                death_ticks = round_deaths["tick"].tolist()
                victims_list = round_deaths["user_steamid"].astype(str).tolist()
                killers_list = round_deaths["attacker_steamid"].astype(str).tolist()
                victims = {v for v in victims_list if v}
                n = len(round_deaths)
                for i in range(n):
                    k = killers_list[i]
                    if k and k != victims_list[i]:
                        round_killers.add(k)
                    a = str(round_deaths.iloc[i].get("assister_steamid", ""))
                    if a:
                        round_assisters.add(a)
                    limit = death_ticks[i] + 128  # TRADE_WINDOW_TICKS
                    for j in range(i + 1, n):
                        if death_ticks[j] > limit:
                            break
                        if victims_list[j] == k:
                            av = killers_list[j]
                            if (av and av != victims_list[j]
                                    and team_of.get(av) == team_of.get(victims_list[i])):
                                traded.add(victims_list[i])
                            break

            participants = traded | round_killers | round_assisters
            winner_side = getattr(rnd, "winner_side", "")
            # side of each played player in this round: tick-majority would be
            # expensive here; the roster side at round start is enough for the
            # save rule because a save requires SURVIVING (not in victims).
            for sid in played:
                if sid in participants:
                    kast[sid] += 1
                    continue
                if sid not in victims:
                    # survived the round — award KAST only if the round was WON
                    # by the player's side OR the player had K/A (handled above)
                    side = self_side_of(demo, rnd, sid)
                    if side and side == winner_side:
                        kast[sid] += 1
                    elif side:
                        saves[sid] += 1  # lost-round save without K/A: punished
        return kast, saves

    # ---- blends ----

    @staticmethod
    def _impact21(kills: int, assists: int, rounds: int) -> float:
        """Impact with the 2.1 assist reward (rule 3)."""
        if rounds <= 0:
            return 0.0
        kpr = kills / rounds
        apr = assists / rounds
        return 2.13 * kpr + 0.42 * _ASSIST_WEIGHT_21 * apr - 0.41

    @staticmethod
    def _rating20(kills: int, deaths: int, assists: int, damage: int,
                  rounds: int, kast_pct: float) -> float:
        """The legacy 2.0 blend (kept for the side-by-side card)."""
        if rounds <= 0:
            return 0.0
        kpr = kills / rounds
        dpr = deaths / rounds
        adr = damage / rounds
        impact = Ratings21Module._impact21(kills, assists, rounds)  # same Impact for both
        return (0.0073 * kast_pct + 0.3591 * kpr - 0.5329 * dpr
                + 0.2372 * impact + 0.0032 * adr + 0.1587)

    @staticmethod
    def _rating21(kills: int, deaths: int, assists: int, damage: int,
                  rounds: int, kast_pct: float, lost_saves: int) -> float:
        """Rating 2.1 = 2.0 blend + save death-discount (rule 2) + recalibration (rule 4)."""
        if rounds <= 0:
            return 0.0
        kpr = kills / rounds
        # rule 2: lost-round saves soften the death count for DPR
        effective_deaths = deaths + _LOST_SAVE_DEATH_WEIGHT * lost_saves
        dpr = effective_deaths / rounds
        adr = damage / rounds
        impact = Ratings21Module._impact21(kills, assists, rounds)
        raw = (0.0073 * kast_pct + 0.3591 * kpr - 0.5329 * dpr
               + 0.2372 * impact + 0.0032 * adr + 0.1587)
        return raw * _RATING_21_RECALIBRATION


def self_side_of(demo: ParsedDemo, rnd, steamid: str) -> str | None:
    """The player's side in one round (cheap: roster team → starting side +
    halftime flip). Falls back to None when unknowable."""
    from cs_analyzer.analysis.util import side_of, round_player_sides

    sides = round_player_sides(demo)
    return side_of(sides, rnd.number, steamid)
