"""BasicStats: per-player kill/death/damage/first-kill statistics.

Computes the raw counts and derived rates (KPR, ADR, Survivals, HS%, FKPR)
that feed the radar chart and other renderers.
"""
from __future__ import annotations

import logging

import pandas as pd
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)


class PlayerStats(BaseModel):
    """Per-player basic statistics."""

    steamid: str
    name: str
    team: str

    # raw counts
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    headshot_kills: int = 0
    first_kills: int = 0
    # Phase I (F8): died first in round — the cost side of opening duels
    first_deaths: int = 0
    damage: int = 0
    rounds: int = 0

    # derived rates
    KPR: float = 0.0
    Survivals: float = 0.0
    ADR: float = 0.0
    headshot_pct: float = 0.0
    FirstKillsPerRound: float = 0.0
    FirstDeathsPerRound: float = 0.0


class BasicStatsResult(AnalysisResult):
    players: list[PlayerStats] = Field(default_factory=list)

    def by_steamid(self, steamid: str) -> PlayerStats | None:
        for p in self.players:
            if p.steamid == steamid:
                return p
        return None


@register_module
class BasicStatsModule(AnalysisModule):
    name = "basic_stats"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        rounds = demo.regular_rounds
        num_rounds = len(rounds)

        deaths_df = demo.events.get("player_death")
        hurts_df = demo.events.get("player_hurt")

        if deaths_df is not None:
            deaths_df = self._filter_warmup(deaths_df)
            deaths_df = self._exclude_teamkills(deaths_df)

        if hurts_df is not None:
            hurts_df = self._filter_warmup(hurts_df)
            hurts_df = self._exclude_teamkills(hurts_df)

        first_killers = (
            self._first_killers_per_round(deaths_df, rounds) if deaths_df is not None else {}
        )
        first_victims = (
            self._first_victims_per_round(deaths_df, rounds) if deaths_df is not None else {}
        )

        stats: list[PlayerStats] = []
        for player in demo.players:
            s = PlayerStats(
                steamid=player.steamid,
                name=player.name,
                team=player.team,
                kills=self._count_attacker(deaths_df, player.steamid),
                deaths=self._count_user(deaths_df, player.steamid),
                assists=self._count_assister(deaths_df, player.steamid),
                headshot_kills=self._count_headshots(deaths_df, player.steamid),
                first_kills=first_killers.get(player.steamid, 0),
                first_deaths=first_victims.get(player.steamid, 0),
                damage=self._sum_damage(hurts_df, player.steamid),
                rounds=num_rounds,
            )
            self._derive_rates(s)
            stats.append(s)

        return BasicStatsResult(
            module=self.name, demo_hash=demo.metadata.demo_hash, players=stats
        )

    @staticmethod
    def _filter_warmup(df: pd.DataFrame) -> pd.DataFrame:
        if "is_warmup_period" in df.columns:
            return df[df["is_warmup_period"] == False]  # noqa: E712
        return df

    @staticmethod
    def _exclude_teamkills(df: pd.DataFrame) -> pd.DataFrame:
        a_col, u_col = "attacker_team_name", "user_team_name"
        if a_col in df.columns and u_col in df.columns:
            return df[df[a_col] != df[u_col]]
        return df

    @staticmethod
    def _count_attacker(deaths_df: pd.DataFrame | None, steamid: str) -> int:
        if deaths_df is None or deaths_df.empty or "attacker_steamid" not in deaths_df.columns:
            return 0
        return int((deaths_df["attacker_steamid"] == steamid).sum())

    @staticmethod
    def _count_user(deaths_df: pd.DataFrame | None, steamid: str) -> int:
        if deaths_df is None or deaths_df.empty or "user_steamid" not in deaths_df.columns:
            return 0
        return int((deaths_df["user_steamid"] == steamid).sum())

    @staticmethod
    def _count_assister(deaths_df: pd.DataFrame | None, steamid: str) -> int:
        if deaths_df is None or deaths_df.empty or "assister_steamid" not in deaths_df.columns:
            return 0
        return int((deaths_df["assister_steamid"] == steamid).sum())

    @staticmethod
    def _count_headshots(deaths_df: pd.DataFrame | None, steamid: str) -> int:
        if deaths_df is None or deaths_df.empty:
            return 0
        if "attacker_steamid" not in deaths_df.columns or "headshot" not in deaths_df.columns:
            return 0
        mask = (deaths_df["attacker_steamid"] == steamid) & (deaths_df["headshot"] == True)  # noqa: E712
        return int(mask.sum())

    @staticmethod
    def _sum_damage(hurts_df: pd.DataFrame | None, steamid: str) -> int:
        if hurts_df is None or hurts_df.empty:
            return 0
        if "attacker_steamid" not in hurts_df.columns or "dmg_health" not in hurts_df.columns:
            return 0
        sub = hurts_df[hurts_df["attacker_steamid"] == steamid]
        return int(sub["dmg_health"].sum())

    @staticmethod
    def _first_killers_per_round(deaths_df: pd.DataFrame, rounds: list) -> dict[str, int]:
        if deaths_df.empty or "tick" not in deaths_df.columns:
            return {}
        result: dict[str, int] = {}
        for rnd in rounds:
            in_round = (deaths_df["tick"] >= rnd.start_tick) & (deaths_df["tick"] <= rnd.end_tick)
            round_deaths = deaths_df[in_round]
            if round_deaths.empty:
                continue
            first = round_deaths.sort_values("tick").iloc[0]
            attacker = first.get("attacker_steamid")
            if attacker and isinstance(attacker, str):
                result[attacker] = result.get(attacker, 0) + 1
        return result

    @staticmethod
    def _first_victims_per_round(deaths_df: pd.DataFrame, rounds: list) -> dict[str, int]:
        """F8: same walk as first kills — who died first each round."""
        if deaths_df.empty or "tick" not in deaths_df.columns:
            return {}
        result: dict[str, int] = {}
        for rnd in rounds:
            in_round = (deaths_df["tick"] >= rnd.start_tick) & (deaths_df["tick"] <= rnd.end_tick)
            round_deaths = deaths_df[in_round]
            if round_deaths.empty:
                continue
            first = round_deaths.sort_values("tick").iloc[0]
            victim = first.get("user_steamid")
            if victim and isinstance(victim, str):
                result[victim] = result.get(victim, 0) + 1
        return result

    @staticmethod
    def _derive_rates(s: PlayerStats) -> None:
        r = s.rounds if s.rounds > 0 else 1
        s.KPR = s.kills / r
        s.Survivals = (s.rounds - s.deaths) / r if s.rounds > 0 else 0.0
        s.ADR = s.damage / r
        s.headshot_pct = (s.headshot_kills / s.kills * 100.0) if s.kills > 0 else 0.0
        s.FirstKillsPerRound = s.first_kills / r
        s.FirstDeathsPerRound = s.first_deaths / r
