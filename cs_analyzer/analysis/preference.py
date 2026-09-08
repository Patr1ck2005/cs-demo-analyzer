"""Player preference analysis: positioning, utility usage, peek style, crosshair placement.

P2 analysis module producing per-player tendency metrics:
  - Position heatmap: sampled (X, Y) positions per round phase
  - Utility placement: smoke/flash/molly detonation positions
  - Peek aggressiveness: average first-engagement tick in round
  - Crosshair placement: average pitch angle (0 = level, negative = looking down)
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import round_player_sides
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
        fires_df = demo.events.get("weapon_fire")
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

            arr = self._player_arrays(ticks, player.steamid)
            pref.position_samples = self._sample_positions(arr, rounds)
            pref.utility_positions, pref.utility_counts = self._utility_placement(
                utility_events, player.steamid
            )
            # B6: first SHOT is the engagement proxy (weapon_fire table was
            # parsed but never consumed); fall back to kill/death involvement
            pref.avg_first_engagement_fraction, pref.engagement_rounds = self._peek_style(
                fires_df, deaths_df, player.steamid, rounds
            )
            pref.avg_pitch, pref.pitch_samples = self._crosshair_placement(arr)
            pref.avg_t_side_position = self._t_side_position(arr, rounds, player.steamid, demo)

            players.append(pref)

        return PreferenceResult(
            module=self.name, demo_hash=demo.metadata.demo_hash, players=players
        )

    @staticmethod
    def _player_arrays(ticks: pd.DataFrame, steamid: str) -> dict:
        """One per-player slice of the tick table as sorted numpy arrays.

        Avoids the old per-lookup full-frame boolean mask (the analysis was
        spending ~45s on 131k-row scans per sample).
        """
        if ticks is None or ticks.empty:
            return {"tick": np.array([]), "X": np.array([]), "Y": np.array([]),
                    "alive": np.array([]), "pitch": np.array([])}
        sub = ticks[ticks["steamid"] == steamid].sort_values("tick")
        arr = {
            "tick": sub["tick"].to_numpy() if not sub.empty else np.array([], dtype=int),
            "X": sub["X"].to_numpy(dtype=float) if "X" in sub.columns else np.array([]),
            "Y": sub["Y"].to_numpy(dtype=float) if "Y" in sub.columns else np.array([]),
        }
        arr["alive"] = sub["is_alive"].to_numpy() if "is_alive" in sub.columns else np.array([])
        arr["pitch"] = sub["pitch"].to_numpy(dtype=float) if "pitch" in sub.columns else np.array([])
        return arr

    @staticmethod
    def _sample_positions(arr: dict, rounds: list) -> list[tuple[float, float]]:
        """Sample (X, Y) positions at phase fractions of each round.

        Uses nearest-tick lookup so off-grid targets still resolve (the old
        exact-match check silently dropped samples whenever the phase tick
        fell between recorded rows).
        """
        t = arr["tick"]
        if t.size == 0 or arr["X"].size == 0:
            return []
        samples: list[tuple[float, float]] = []
        for rnd in rounds:
            duration = rnd.end_tick - rnd.start_tick
            for phase in PHASE_SAMPLES:
                target = rnd.start_tick + int(duration * phase)
                i = int(np.searchsorted(t, target, side="right")) - 1
                # clamp to this round: never leak a position from an earlier round
                if i >= 0 and rnd.start_tick <= t[i] <= rnd.end_tick:
                    x, y = arr["X"][i], arr["Y"][i]
                    if np.isfinite(x):
                        samples.append((float(x), float(y)))
        return samples

    @staticmethod
    def _utility_placement(
        utility_events: dict[str, pd.DataFrame | None],
        steamid: str,
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
    def _first_involvement_tick(df: pd.DataFrame, steamid: str, rnd) -> int | None:
        """First in-round tick where the player appears (attacker or user)."""
        in_round = (df["tick"] >= rnd.start_tick) & (df["tick"] <= rnd.end_tick)
        sub = df[in_round]
        if sub.empty:
            return None
        mask = pd.Series(False, index=sub.index)
        for col in ("attacker_steamid", "user_steamid", "user_steamid"):
            if col in sub.columns:
                mask |= sub[col] == steamid
        involved = sub[mask]
        if involved.empty:
            return None
        return int(involved["tick"].min())

    @staticmethod
    def _peek_style(
        fires_df: pd.DataFrame | None,
        deaths_df: pd.DataFrame | None,
        steamid: str,
        rounds: list,
    ) -> tuple[float, int]:
        """Average first-engagement tick fraction of round.

        B6: engagement = first SHOT (weapon_fire); a kill-or-death proxy only
        when the fire table is absent. Lower = more aggressive.
        """
        primary = fires_df if fires_df is not None and not fires_df.empty else None
        fallback = deaths_df if deaths_df is not None and not deaths_df.empty else None
        if primary is None and fallback is None:
            return 0.5, 0

        fractions: list[float] = []
        for rnd in rounds:
            duration = rnd.end_tick - rnd.start_tick
            if duration <= 0:
                continue
            first_tick = None
            if primary is not None and {"user_steamid"} & set(primary.columns):
                first_tick = PreferenceModule._first_involvement_tick(primary, steamid, rnd)
            if first_tick is None and fallback is not None:
                first_tick = PreferenceModule._first_involvement_tick(fallback, steamid, rnd)
            if first_tick is None:
                continue
            fractions.append((first_tick - rnd.start_tick) / duration)

        if not fractions:
            return 0.5, 0
        return float(np.mean(fractions)), len(fractions)

    @staticmethod
    def _crosshair_placement(arr: dict) -> tuple[float, int]:
        """Average pitch angle (degrees) across alive, finite samples.

        demoparser2 pitch arrives already in degrees (-89..89; verified on the
        real cache parquet). Phase I removed the spurious np.degrees()
        double conversion that crushed every value toward ~0.
        """
        pitch, alive = arr["pitch"], arr["alive"]
        if pitch.size == 0 or alive.size == 0:
            return 0.0, 0
        sel = pitch[np.isfinite(pitch) & alive.astype(bool)]
        if sel.size == 0:
            return 0.0, 0
        return float(np.mean(sel)), sel.size

    @staticmethod
    def _t_side_position(
        arr: dict, rounds: list, steamid: str, demo: ParsedDemo
    ) -> tuple[float, float] | None:
        """Average position at 25% round time on T-side rounds (default vs execute indicator)."""
        t, xs_a, ys_a = arr["tick"], arr["X"], arr["Y"]
        if t.size == 0 or xs_a.size == 0:
            return None
        meta = demo.metadata
        team = next((p.team for p in demo.players if p.steamid == steamid), None)
        if team is None:
            return None
        if team not in (meta.team_a.name, meta.team_b.name):
            return None

        xs: list[float] = []
        ys: list[float] = []
        # swap-safe side lookup (util.round_player_sides) — the old
        # `round.number <= 12` MR12 hardcode mis-classified overtime rounds
        sides_by_round = round_player_sides(demo)
        for rnd in rounds:
            if sides_by_round.get(rnd.number, {}).get(steamid) != "T":
                continue
            target = rnd.start_tick + int((rnd.end_tick - rnd.start_tick) * 0.25)
            i = int(np.searchsorted(t, target, side="right")) - 1
            if i >= 0 and rnd.start_tick <= t[i] <= rnd.end_tick and np.isfinite(xs_a[i]):
                xs.append(float(xs_a[i]))
                ys.append(float(ys_a[i]))
        if not xs:
            return None
        return float(np.mean(xs)), float(np.mean(ys))
