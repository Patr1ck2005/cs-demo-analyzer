"""Ratings: RWS (Round Win Shares) and HLTV Rating 2.0 approximation.

Both are computed from demo events. RWS measures damage contribution to won
rounds; Rating 2.0 blends KPR, DPR, KAST, Impact, and ADR.

Note: These are approximations of proprietary metrics. External platforms
(Faceit, Perfect World, etc.) may compute RWS/Rating differently.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import pandas as pd
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.basic_stats import BasicStatsResult
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

# Trade window: a death is "traded" if the killer dies within this many ticks.
TRADE_WINDOW_TICKS = 128  # ~2s at 64 tick


class PlayerRatings(BaseModel):
    steamid: str
    name: str
    team: str
    RWS: float = 0.0
    Rating: float = 0.0
    Rating_Pro: float = 0.0  # alias of Rating, for radar-chart compatibility
    KAST: float = 0.0
    Impact: float = 0.0


class RatingsResult(AnalysisResult):
    players: list[PlayerRatings] = Field(default_factory=list)

    def by_steamid(self, steamid: str) -> PlayerRatings | None:
        for p in self.players:
            if p.steamid == steamid:
                return p
        return None


@register_module
class RatingsModule(AnalysisModule):
    name = "ratings"
    requires = ("basic_stats",)

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        basic = ctx.require("basic_stats")
        assert isinstance(basic, BasicStatsResult)
        rounds = demo.regular_rounds
        hurts_df = demo.events.get("player_hurt")
        deaths_df = demo.events.get("player_death")

        team_members = self._team_members(demo)
        per_round_damage = self._per_round_damage(hurts_df, rounds) if hurts_df is not None else {}
        kast_rounds = self._kast_per_player(deaths_df, rounds, demo) if deaths_df is not None else defaultdict(int)

        ratings: list[PlayerRatings] = []
        for stats in basic.players:
            rws = self._compute_rws(stats.steamid, stats.team, rounds, per_round_damage, team_members)
            kast_pct = (kast_rounds.get(stats.steamid, 0) / stats.rounds * 100.0) if stats.rounds > 0 else 0.0
            rating = self._compute_rating(stats.kills, stats.deaths, stats.assists,
                                          stats.damage, stats.rounds, kast_pct)

            ratings.append(PlayerRatings(
                steamid=stats.steamid,
                name=stats.name,
                team=stats.team,
                RWS=rws,
                Rating=rating,
                Rating_Pro=rating,
                KAST=kast_pct,
                Impact=self._impact(stats.kills, stats.assists, stats.rounds),
            ))

        return RatingsResult(
            module=self.name, demo_hash=demo.metadata.demo_hash, players=ratings
        )

    # ---- RWS ----

    @staticmethod
    def _team_members(demo: ParsedDemo) -> dict[str, set[str]]:
        """Map team name -> set of steamids."""
        members: dict[str, set[str]] = defaultdict(set)
        for p in demo.players:
            members[p.team].add(p.steamid)
        return members

    @staticmethod
    def _per_round_damage(hurts_df: pd.DataFrame, rounds: list) -> dict[int, dict[str, int]]:
        """{round_number: {steamid: damage_in_round}}."""
        result: dict[int, dict[str, int]] = {}
        if hurts_df is None or hurts_df.empty:
            return result
        if "attacker_steamid" not in hurts_df.columns or "dmg_health" not in hurts_df.columns:
            return result
        for rnd in rounds:
            in_round = (hurts_df["tick"] >= rnd.start_tick) & (hurts_df["tick"] <= rnd.end_tick)
            sub = hurts_df[in_round]
            if sub.empty:
                result[rnd.number] = {}
                continue
            by_attacker = sub.groupby("attacker_steamid")["dmg_health"].sum().to_dict()
            result[rnd.number] = {str(k): int(v) for k, v in by_attacker.items()}
        return result

    @staticmethod
    def _compute_rws(
        steamid: str,
        team: str,
        rounds: list,
        per_round_damage: dict[int, dict[str, int]],
        team_members: dict[str, set[str]],
    ) -> float:
        if not rounds:
            return 0.0
        members = team_members.get(team, set())
        total_rws = 0.0
        for rnd in rounds:
            if rnd.winner != team:
                continue  # RWS only for rounds won
            round_dmg = per_round_damage.get(rnd.number, {})
            player_dmg = round_dmg.get(steamid, 0)
            team_dmg = sum(round_dmg.get(sid, 0) for sid in members)
            if team_dmg > 0:
                total_rws += (player_dmg / team_dmg) * 100.0
        return total_rws / len(rounds)

    # ---- Rating 2.0 ----

    @staticmethod
    def _impact(kills: int, assists: int, rounds: int) -> float:
        """Impact = 2.13 * KPR + 0.42 * APR - 0.41."""
        if rounds <= 0:
            return 0.0
        kpr = kills / rounds
        apr = assists / rounds
        return 2.13 * kpr + 0.42 * apr - 0.41

    @staticmethod
    def _compute_rating(
        kills: int, deaths: int, assists: int, damage: int, rounds: int, kast_pct: float
    ) -> float:
        """HLTV Rating 2.0 approximation.

        Rating = 0.0073*KAST + 0.3591*KPR - 0.5329*DPR + 0.2372*Impact + 0.0032*ADR + 0.1587
        """
        if rounds <= 0:
            return 0.0
        kpr = kills / rounds
        dpr = deaths / rounds
        adr = damage / rounds
        impact = RatingsModule._impact(kills, assists, rounds)
        return (
            0.0073 * kast_pct
            + 0.3591 * kpr
            - 0.5329 * dpr
            + 0.2372 * impact
            + 0.0032 * adr
            + 0.1587
        )

    # ---- KAST ----

    @staticmethod
    def _kast_per_player(
        deaths_df: pd.DataFrame, rounds: list, demo: ParsedDemo
    ) -> dict[str, int]:
        """For each player, count rounds where they K'd/A'd/S'd or were traded."""
        if deaths_df is None or deaths_df.empty:
            return {}
        if "tick" not in deaths_df.columns:
            return {}

        kast: dict[str, int] = defaultdict(int)
        for rnd in rounds:
            in_round = (deaths_df["tick"] >= rnd.start_tick) & (deaths_df["tick"] <= rnd.end_tick)
            round_deaths = deaths_df[in_round].sort_values("tick")
            if round_deaths.empty:
                # nobody died -> everyone on surviving side "survived"
                for p in demo.players:
                    kast[p.steamid] += 1
                continue

            killers_after: dict[str, int] = {}  # steamid -> tick they died (if within trade window)
            for _, row in round_deaths.iterrows():
                victim = str(row.get("user_steamid", ""))
                killer = str(row.get("attacker_steamid", ""))
                # mark killer's death time if they die later in the round within trade window
                killer_tick = int(row["tick"])
                # check if killer dies within TRADE_WINDOW_TICKS after this kill
                later = round_deaths[
                    (round_deaths["tick"] > killer_tick)
                    & (round_deaths["tick"] <= killer_tick + TRADE_WINDOW_TICKS)
                ]
                if not later.empty:
                    # find if the killer appears as a victim
                    killer_dies = later[later["user_steamid"] == killer]
                    if not killer_dies.empty:
                        killers_after[killer] = int(killer_dies.iloc[0]["tick"])

            participants: set[str] = set()
            for _, row in round_deaths.iterrows():
                attacker = str(row.get("attacker_steamid", ""))
                victim = str(row.get("user_steamid", ""))
                assister = str(row.get("assister_steamid", ""))
                if attacker:
                    participants.add(attacker)  # Kill
                if assister:
                    participants.add(assister)  # Assist
                if victim and victim not in killers_after:
                    # Survived? No — they died. Traded? Only if their killer died.
                    pass
                else:
                    # victim was traded (their killer died)
                    if victim:
                        participants.add(victim)

            # Survived = didn't die in this round
            victims_in_round = {str(v) for v in round_deaths["user_steamid"].tolist()}
            for p in demo.players:
                if p.steamid in participants:
                    kast[p.steamid] += 1
                elif p.steamid not in victims_in_round:
                    kast[p.steamid] += 1  # Survived
        return kast
