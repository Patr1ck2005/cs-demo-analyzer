"""Player preference analysis: positioning, utility usage, peek style, crosshair placement.

P2 analysis module producing per-player tendency metrics:
  - Position heatmap: sampled (X, Y) positions per round phase
  - Utility placement: smoke/flash/molly detonation positions
  - Peek aggressiveness: average first-engagement tick in round
  - Crosshair placement: average pitch angle (0 = level, negative = looking down)
"""
from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

# Sample positions at these phase fractions of each round
PHASE_SAMPLES = (0.1, 0.25, 0.5, 0.75, 0.9)


class PlayerPreference(BaseModel):
    steamid: str
    name: str
    team: str

    # Positioning: sampled positions for heatmap rendering
    position_samples: list[tuple[float, float]] = Field(default_factory=list)

    # Utility: grenade detonation positions per type
    utility_positions: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)
    utility_counts: dict[str, int] = Field(default_factory=dict)

    # Peek: average first-engagement tick fraction (0-1 of round duration)
    # Lower = more aggressive (engages early); higher = more passive
    avg_first_engagement_fraction: float = 0.5
    engagement_rounds: int = 0

    # Crosshair placement: average pitch (degrees)
    # 0 = level; negative = looking down; positive = looking up
    avg_pitch: float = 0.0
    pitch_samples: int = 0

    # T-side defaults vs executes: average time to first crossing of mid
    # (simplified: average X position at 25% round time on T side)
    avg_t_side_position: tuple[float, float] | None = None


class PreferenceResult(AnalysisResult):
    players: list[PlayerPreference] = Field(default_factory=list)

    def by_steamid(self, steamid: str) -> PlayerPreference | None:
        for p in self.players:
            if p.steamid == steamid:
                return p
        return None


@register_module
class PreferenceModule(AnalysisModule):
    name = "preference"
    requires = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        rounds = demo.regular_rounds
        ticks = demo.ticks
        deaths_df = demo.events.get("player_death")
        utility_events = {
            "smoke": demo.events.get("smokegrenade_detonate"),
            "flash": demo.events.get("flashbang_detonate"),
            "he": demo.events.get("hegrenade_detonate"),
            "molly": demo.events.get("molotov_detonate"),
        }

        players: list[PlayerPreference] = []
        for player in demo.players:
            pref = PlayerPreference(steamid=player.steamid, name=player.name, team=player.team)

            pref.position_samples = self._sample_positions(ticks, player.steamid, rounds)
            pref.utility_positions, pref.utility_counts = self._utility_placement(
                utility_events, player.steamid, ticks
            )
            pref.avg_first_engagement_fraction, pref.engagement_rounds = self._peek_style(
                deaths_df, player.steamid, rounds
            )
            pref.avg_pitch, pref.pitch_samples = self._crosshair_placement(ticks, player.steamid, rounds)
            pref.avg_t_side_position = self._t_side_position(ticks, player.steamid, rounds, demo)

            players.append(pref)

        return PreferenceResult(
            module=self.name, demo_hash=demo.metadata.demo_hash, players=players
        )

    @staticmethod
    def _sample_positions(ticks: pd.DataFrame, steamid: str, rounds: list) -> list[tuple[float, float]]:
        """Sample (X, Y) positions at phase fractions of each round."""
        if ticks.empty or "X" not in ticks.columns:
            return []
        samples: list[tuple[float, float]] = []
        for rnd in rounds:
            duration = rnd.end_tick - rnd.start_tick
            for phase in PHASE_SAMPLES:
                target_tick = rnd.start_tick + int(duration * phase)
                mask = (ticks["steamid"] == steamid) & (ticks["tick"] == target_tick)
                row = ticks[mask]
                if not row.empty and pd.notna(row.iloc[0]["X"]):
                    samples.append((float(row.iloc[0]["X"]), float(row.iloc[0]["Y"])))
        return samples

    @staticmethod
    def _utility_placement(
        utility_events: dict[str, pd.DataFrame | None],
        steamid: str,
        ticks: pd.DataFrame,
    ) -> tuple[dict[str, list[tuple[float, float]]], dict[str, int]]:
        """Get grenade detonation positions thrown by the player."""
        positions: dict[str, list[tuple[float, float]]] = {}
        counts: dict[str, int] = {}
        for grenade_type, df in utility_events.items():
            if df is None or df.empty:
                continue
            if "thrower_steamid" in df.columns:
                thrown = df[df["thrower_steamid"] == steamid]
            elif "user_steamid" in df.columns:
                thrown = df[df["user_steamid"] == steamid]
            else:
                continue
            if thrown.empty:
                continue
            pos_list: list[tuple[float, float]] = []
            x_col = "X" if "X" in thrown.columns else "user_X" if "user_X" in thrown.columns else None
            y_col = "Y" if "Y" in thrown.columns else "user_Y" if "user_Y" in thrown.columns else None
            if x_col is None or y_col is None:
                continue
            for _, row in thrown.iterrows():
                if pd.notna(row[x_col]) and pd.notna(row[y_col]):
                    pos_list.append((float(row[x_col]), float(row[y_col])))
            positions[grenade_type] = pos_list
            counts[grenade_type] = len(pos_list)
        return positions, counts

    @staticmethod
    def _peek_style(
        deaths_df: pd.DataFrame | None, steamid: str, rounds: list
    ) -> tuple[float, int]:
        """Average first-engagement tick fraction (when player first shoots/kills in round).

        Lower fraction = aggressive (engages early); higher = passive.
        Uses first player_death event involving the player as engagement proxy.
        """
        if deaths_df is None or deaths_df.empty:
            return 0.5, 0
        if "attacker_steamid" not in deaths_df.columns and "user_steamid" not in deaths_df.columns:
            return 0.5, 0

        fractions: list[float] = []
        for rnd in rounds:
            duration = rnd.end_tick - rnd.start_tick
            if duration <= 0:
                continue
            in_round = (deaths_df["tick"] >= rnd.start_tick) & (deaths_df["tick"] <= rnd.end_tick)
            round_deaths = deaths_df[in_round]
            if round_deaths.empty:
                continue
            # Find first event where player is attacker or victim
            mask = pd.Series(False, index=round_deaths.index)
            if "attacker_steamid" in round_deaths.columns:
                mask |= round_deaths["attacker_steamid"] == steamid
            if "user_steamid" in round_deaths.columns:
                mask |= round_deaths["user_steamid"] == steamid
            involved = round_deaths[mask]
            if involved.empty:
                continue
            first_tick = int(involved["tick"].min())
            fractions.append((first_tick - rnd.start_tick) / duration)

        if not fractions:
            return 0.5, 0
        return float(np.mean(fractions)), len(fractions)

    @staticmethod
    def _crosshair_placement(ticks: pd.DataFrame, steamid: str, rounds: list) -> tuple[float, int]:
        """Average pitch angle (degrees) across sampled ticks.

        CS2 pitch: 0 = level, positive = looking up, negative = looking down.
        Good crosshair placement is typically near 0 (level at head height).
        """
        if ticks.empty or "pitch" not in ticks.columns:
            return 0.0, 0
        player_ticks = ticks[(ticks["steamid"] == steamid) & (ticks["is_alive"] == True)]  # noqa: E712
        if player_ticks.empty:
            return 0.0, 0
        pitch = player_ticks["pitch"].dropna()
        if pitch.empty:
            return 0.0, 0
        # Convert radians to degrees (demoparser pitch is in radians)
        avg_degrees = float(np.degrees(np.mean(pitch)))
        return avg_degrees, len(pitch)

    @staticmethod
    def _t_side_position(
        ticks: pd.DataFrame, steamid: str, rounds: list, demo: ParsedDemo
    ) -> tuple[float, float] | None:
        """Average position at 25% round time on T-side rounds (default vs execute indicator)."""
        if ticks.empty or "X" not in ticks.columns:
            return None
        meta = demo.metadata
        team = next((p.team for p in demo.players if p.steamid == steamid), None)
        if team is None:
            return None
        if team == meta.team_a.name:
            starts = meta.team_a.starting_side
        elif team == meta.team_b.name:
            starts = meta.team_b.starting_side
        else:
            return None

        xs: list[float] = []
        ys: list[float] = []
        for rnd in rounds:
            side = "T" if starts == "T" else ("CT" if rnd.number <= 12 else "T") if starts == "CT" else "T"
            if starts == "CT":
                side = "CT" if rnd.number <= 12 else "T"
            else:
                side = "T" if rnd.number <= 12 else "CT"
            if side != "T":
                continue
            duration = rnd.end_tick - rnd.start_tick
            target_tick = rnd.start_tick + int(duration * 0.25)
            mask = (ticks["steamid"] == steamid) & (ticks["tick"] == target_tick)
            row = ticks[mask]
            if not row.empty and pd.notna(row.iloc[0]["X"]):
                xs.append(float(row.iloc[0]["X"]))
                ys.append(float(row.iloc[0]["Y"]))
        if not xs:
            return None
        return float(np.mean(xs)), float(np.mean(ys))
