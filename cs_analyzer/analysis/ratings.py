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
from cs_analyzer.analysis.basic_stats import BasicStatsModule, BasicStatsResult
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

        # Phase I (B5): align filtering with basic_stats — warmup rows and
        # teamkills must not feed RWS damage or KAST. (Previously unfiltered
        # here, giving ADR/damage inputs a different basis per module.)
        if hurts_df is not None:
            hurts_df = BasicStatsModule._filter_warmup(hurts_df)
            hurts_df = BasicStatsModule._exclude_teamkills(hurts_df)
        if deaths_df is not None:
            deaths_df = BasicStatsModule._filter_warmup(deaths_df)
            deaths_df = BasicStatsModule._exclude_teamkills(deaths_df)

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
        """For each player, count rounds where they K'd/A'd/S'd or were traded.

        Trade semantics (standard): a victim is "traded" when the killer who
        killed them dies within TRADE_WINDOW_TICKS afterwards. (Phase I fix:
        the previous implementation inverted this and credited players who
        made a kill then died soon after.)
        """
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

            death_ticks = round_deaths["tick"].tolist()
            victims = round_deaths["user_steamid"].astype(str).tolist()
            killers = round_deaths["attacker_steamid"].astype(str).tolist()
            n = len(round_deaths)

            # traded = set of victims whose killer died within the window
            traded: set[str] = set()
            for i in range(n):
                killer_i = killers[i]
                if not killer_i or killer_i == victims[i]:
                    continue
                limit = death_ticks[i] + TRADE_WINDOW_TICKS
                for j in range(i + 1, n):
                    if death_ticks[j] > limit:
                        break
                    if victims[j] == killer_i:
                        traded.add(victims[i])
                        break

            participants: set[str] = set(traded)
            for i in range(n):
                if killers[i] and killers[i] != victims[i]:
                    participants.add(killers[i])  # Kill
                assister = str(round_deaths.iloc[i].get("assister_steamid", ""))
                if assister:
                    participants.add(assister)  # Assist

            victims_in_round = {v for v in victims if v}
            for p in demo.players:
                if p.steamid in participants:
                    kast[p.steamid] += 1
                elif p.steamid not in victims_in_round:
                    kast[p.steamid] += 1  # Survived
        return kast
