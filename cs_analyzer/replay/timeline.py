"""PlayerTimeline: structured per-player replay data extracted from ParsedDemo.

Decouples data extraction from rendering. Produces sorted position arrays and
event lists ready for the replay renderer (and reusable by other renderers).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import Player, Round

from .sides import side_for_round


@dataclass
class Event:
    tick: int
    x: float
    y: float
    meta: str = ""


@dataclass
class Shot(Event):
    weapon: str = ""


@dataclass
class Kill:
    tick: int
    x: float
    y: float
    victim_x: float
    victim_y: float
    victim_name: str
    weapon: str


# Utility type -> event table name(s); first present table wins.
UTILITY_TABLES: dict[str, tuple[str, ...]] = {
    "smoke": ("smokegrenade_detonate",),
    "flash": ("flashbang_detonate",),
    "he": ("hegrenade_detonate",),
    "molly": ("molotov_detonate",),
    "fire": ("inferno_startburn",),
}


class PlayerTimeline:
    """Sorted position arrays + event lists for one player."""

    def __init__(
        self,
        player: Player,
        demo: ParsedDemo,
        ticks: np.ndarray,
        xs: np.ndarray,
        ys: np.ndarray,
        alive: np.ndarray,
        team_nums: np.ndarray,
    ) -> None:
        self.player = player
        self.demo = demo
        self.ticks = ticks
        self.xs = xs
        self.ys = ys
        self.alive = alive
        self.team_nums = team_nums
        self.starting_side = _team_starting_side(demo, player.team)
        self.shots: list[Shot] = []
        self.jumps: list[Event] = []
        self.kills: list[Kill] = []
        self.deaths: list[Event] = []
        self.utilities: dict[str, list[Event]] = {}

    # ---- position queries ----

    def position_at(self, tick: float) -> tuple[float, float]:
        return float(np.interp(tick, self.ticks, self.xs)), float(
            np.interp(tick, self.ticks, self.ys)
        )

    def frame_positions(self, frame_ticks: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Vectorized (xs, ys, alive) for an array of fractional tick values."""
        return (
            np.interp(frame_ticks, self.ticks, self.xs),
            np.interp(frame_ticks, self.ticks, self.ys),
            np.interp(frame_ticks, self.ticks, self.alive) > 0.5,
        )

    def side_at_tick(self, tick: float) -> str:
        """Side (T/CT) at a tick. team_num is the current side and toggles at
        halftime; fall back to round-side math when team_num is missing."""
        idx = int(np.searchsorted(self.ticks, tick, side="right")) - 1
        if 0 <= idx < len(self.team_nums):
            tn = self.team_nums[idx]
            if tn == 2:
                return "T"
            if tn == 3:
                return "CT"
        rnd = self.demo.data.round_at_tick(int(tick))
        if rnd is not None:
            return side_for_round(rnd.number, self.starting_side, rnd.is_overtime)
        return self.starting_side

    def side_for_round(self, rnd: Round) -> str:
        return side_for_round(rnd.number, self.starting_side, rnd.is_overtime)

    # ---- helper for renderer ----

    def utility_events_sorted(self) -> dict[str, list[Event]]:
        """Utility events with per-kind lists sorted by tick."""
        return {kind: sorted(evs, key=lambda e: e.tick) for kind, evs in self.utilities.items()}


# ---- builders ----

def build_timeline(demo: ParsedDemo, steamid_or_name: str) -> PlayerTimeline:
    """Extract a PlayerTimeline for a player (by steamid or name)."""
    player = demo.player(steamid_or_name)
    if player is None:
        raise ValueError(
            f"Player '{steamid_or_name}' not found. Available: {[p.name for p in demo.players]}"
        )

    ticks = demo.ticks
    pticks = ticks[ticks["steamid"] == player.steamid].sort_values("tick") if not ticks.empty else pd.DataFrame()
    if not pticks.empty:
        xs = pticks["X"].to_numpy(dtype=float)
        if not np.any(~np.isnan(xs)):
            raise ValueError(
                f"Player '{player.name}' has no position data in this demo "
                "(tick X/Y all missing). Some SourceTV demos omit entity "
                "tracking for certain players; pick another player."
            )
    tl = PlayerTimeline(
        player=player,
        demo=demo,
        ticks=pticks["tick"].to_numpy(dtype=float) if not pticks.empty else np.array([]),
        xs=pticks["X"].to_numpy(dtype=float) if not pticks.empty else np.array([]),
        ys=pticks["Y"].to_numpy(dtype=float) if not pticks.empty else np.array([]),
        alive=pticks["is_alive"].to_numpy(dtype=float) if not pticks.empty and "is_alive" in pticks else np.array([]),
        team_nums=pticks["team_num"].to_numpy(dtype=float) if not pticks.empty and "team_num" in pticks else np.array([]),
    )
    _extract_shots(tl, demo.events.get("weapon_fire"))
    _extract_jumps(tl, demo.events.get("player_jump"))
    _extract_kills_deaths(tl, demo.events.get("player_death"))
    _extract_utilities(tl, demo.events)
    return tl


def _team_starting_side(demo: ParsedDemo, team: str) -> str:
    meta = demo.metadata
    if team == meta.team_a.name:
        return meta.team_a.starting_side
    if team == meta.team_b.name:
        return meta.team_b.starting_side
    return "CT"


def _position(row: pd.Series, tl: PlayerTimeline, x_col: str, y_col: str) -> tuple[float, float]:
    """Get (x, y) for an event row, guarding NaN and falling back to tick lookup."""
    if x_col in row and y_col in row and pd.notna(row[x_col]) and pd.notna(row[y_col]):
        return float(row[x_col]), float(row[y_col])
    return tl.position_at(float(row["tick"]))


def _extract_shots(tl: PlayerTimeline, df: pd.DataFrame | None) -> None:
    if df is None or df.empty or "user_steamid" not in df.columns:
        return
    sub = df[df["user_steamid"] == tl.player.steamid]
    for _, row in sub.iterrows():
        x, y = _position(row, tl, "user_X", "user_Y")
        tl.shots.append(
            Shot(tick=int(row["tick"]), x=x, y=y, weapon=str(row.get("weapon", "")))
        )
    tl.shots.sort(key=lambda s: s.tick)


def _extract_jumps(tl: PlayerTimeline, df: pd.DataFrame | None) -> None:
    if df is None or df.empty or "user_steamid" not in df.columns:
        return
    sub = df[df["user_steamid"] == tl.player.steamid]
    has_pos = "user_X" in sub.columns and "user_Y" in sub.columns
    for _, row in sub.iterrows():
        x, y = _position(row, tl, "user_X", "user_Y") if has_pos else tl.position_at(float(row["tick"]))
        tl.jumps.append(Event(tick=int(row["tick"]), x=x, y=y))
    tl.jumps.sort(key=lambda e: e.tick)


def _extract_kills_deaths(tl: PlayerTimeline, df: pd.DataFrame | None) -> None:
    if df is None or df.empty:
        return
    for _, row in df.iterrows():
        tick = int(row["tick"])
        if "attacker_steamid" in row and row["attacker_steamid"] == tl.player.steamid:
            ax, ay = _position(row, tl, "attacker_X", "attacker_Y")
            vx, vy = _position(row, tl, "user_X", "user_Y")
            tl.kills.append(
                Kill(
                    tick=tick, x=ax, y=ay, victim_x=vx, victim_y=vy,
                    victim_name=str(row.get("user_name", "")),
                    weapon=str(row.get("weapon", "")),
                )
            )
        if "user_steamid" in row and row["user_steamid"] == tl.player.steamid:
            x, y = _position(row, tl, "user_X", "user_Y")
            tl.deaths.append(Event(tick=tick, x=x, y=y))
    tl.kills.sort(key=lambda k: k.tick)
    tl.deaths.sort(key=lambda e: e.tick)


def _extract_utilities(tl: PlayerTimeline, events: dict[str, pd.DataFrame]) -> None:
    for kind, tables in UTILITY_TABLES.items():
        for table in tables:
            df = events.get(table)
            if df is None or df.empty or "user_steamid" not in df.columns:
                continue
            sub = df[df["user_steamid"] == tl.player.steamid]
            evs: list[Event] = []
            for _, row in sub.iterrows():
                # Impact point is the lowercase x/y (thrower position is user_X/Y).
                x, y = _position(row, tl, "x", "y")
                evs.append(Event(tick=int(row["tick"]), x=x, y=y))
            tl.utilities[kind] = evs
            break  # first present table for this kind wins
    for evs in tl.utilities.values():
        evs.sort(key=lambda e: e.tick)
