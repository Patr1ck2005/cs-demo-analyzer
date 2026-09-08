"""PlayerTimeline: structured per-player replay data extracted from ParsedDemo.

Decouples data extraction from rendering. Produces sorted position arrays and
event lists ready for the replay renderer (and reusable by other renderers).
"""
from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class Utility(Event):
    """A grenade thrown by the target player.

    tick/x/y are the LANDING (impact) point and tick. throw_* is the
    reconstructed throw origin (player's position `nade_flight_seconds`
    before impact — approximate, demoparser2 has no grenade flight data).
    duration_ticks is the real in-game lifetime when known (smoke/fire from
    *_expired events), else 0 meaning "use renderer default".
    """

    kind: str = ""
    throw_tick: int = -1
    throw_x: float = 0.0
    throw_y: float = 0.0
    duration_ticks: int = 0


# Utility type -> event table name(s); first present table wins.
UTILITY_TABLES: dict[str, tuple[str, ...]] = {
    "smoke": ("smokegrenade_detonate",),
    "flash": ("flashbang_detonate",),
    "he": ("hegrenade_detonate",),
    "molly": ("molotov_detonate",),
    "fire": ("inferno_startburn",),
}

# End-of-effect tables used to derive real durations (matched by entityid).
UTILITY_END_TABLES: dict[str, str] = {
    "smoke": "smokegrenade_expired",
    "fire": "inferno_expire",
}

# Sane duration windows (seconds) for end-matched durations; entityids are
# reused across rounds so a match outside this window is a false positive.
UTILITY_DURATION_WINDOW: dict[str, tuple[float, float]] = {
    "smoke": (10.0, 60.0),
    "fire": (1.0, 30.0),
}

# Fallback durations (seconds) when no real end event is available.
UTILITY_DEFAULT_SECONDS: dict[str, float] = {
    "smoke": 18.0,
    "flash": 2.0,
    "he": 1.0,
    "molly": 7.0,
    "fire": 7.0,
}

# Estimated grenade flight time (seconds) used to reconstruct the throw origin.
NADE_FLIGHT_SECONDS: dict[str, float] = {
    "smoke": 2.0,
    "flash": 1.5,
    "he": 1.5,
    "molly": 1.5,
    "fire": 1.5,
}

TICK_RATE = 64  # CS2 SourceTV/GOTV tick rate


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

    def alive_window(self, rnd: Round, freeze_end: int | None = None) -> tuple[int, int]:
        """Alive tick window [start, end] for this player in a round.

        Trims the round's prep/freeze time (start at freeze_end) and the
        player's post-death time (end at their death tick).
        """
        start = int(freeze_end) if freeze_end else int(rnd.start_tick)
        end = int(rnd.end_tick)
        for d in self.deaths:
            if start <= d.tick < end:
                end = d.tick  # include the death tick so the skull shows
                break
        return start, end


# ---- builders ----

def round_freeze_ends(demo: ParsedDemo) -> dict[int, int]:
    """Map round number -> freeze-end tick (when the round goes live).

    `round_freeze_end` fires once per round; the round's prep/buy time before
    it is 'invalid' and is trimmed by starting replays at this tick.

    Pairing is by span containment, not by event index: warmup phases emit an
    extra freeze_end (and reuse round numbers), so a naive zip paired every
    round with the previous round's freeze end — round 1 even inherited the
    warmup's, making replays start mid-warmup with most players unspawned.
    """
    df = demo.events.get("round_freeze_end")
    if df is None or df.empty or "tick" not in df.columns:
        return {}
    ends = sorted(int(t) for t in df["tick"])
    out: dict[int, int] = {}
    ordered = sorted(demo.regular_rounds, key=lambda r: r.start_tick)
    for i, r in enumerate(ordered):
        inside = [e for e in ends if r.start_tick <= e <= r.end_tick]
        if inside:
            out[r.number] = inside[0]
        elif i < len(ends):
            # No freeze_end inside the span (unusual broadcast): keep the old
            # index-based pairing as a fallback rather than losing the round.
            out[r.number] = ends[i]
    return out


def build_timeline(
    demo: ParsedDemo,
    steamid_or_name: str,
    nade_flight_seconds: dict[str, float] | None = None,
) -> PlayerTimeline:
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
    _extract_utilities(tl, demo.events, nade_flight_seconds)
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


def _extract_utilities(
    tl: PlayerTimeline,
    events: dict[str, pd.DataFrame],
    nade_flight_seconds: dict[str, float] | None = None,
) -> None:
    flight = {**(NADE_FLIGHT_SECONDS), **(nade_flight_seconds or {})}
    for kind, tables in UTILITY_TABLES.items():
        for table in tables:
            df = events.get(table)
            if df is None or df.empty or "user_steamid" not in df.columns:
                continue
            sub = df[df["user_steamid"] == tl.player.steamid]
            end_by_id = _end_tick_by_entity(events.get(UTILITY_END_TABLES.get(kind, "")))
            evs: list[Utility] = []
            for _, row in sub.iterrows():
                # Impact point is the lowercase x/y (thrower position is user_X/Y).
                x, y = _position(row, tl, "x", "y")
                land_tick = int(row["tick"])
                dur_ticks = _real_duration(kind, land_tick, row.get("entityid"), end_by_id)
                throw_tick, tx, ty = _reconstruct_throw(tl, kind, land_tick, x, y, flight)
                evs.append(
                    Utility(
                        tick=land_tick, x=x, y=y,
                        kind=kind,
                        throw_tick=throw_tick, throw_x=tx, throw_y=ty,
                        duration_ticks=dur_ticks,
                    )
                )
            tl.utilities[kind] = evs
            break  # first present table for this kind wins
    for evs in tl.utilities.values():
        evs.sort(key=lambda e: e.tick)


def _end_tick_by_entity(df: pd.DataFrame | None) -> dict[int, int]:
    """Map entityid -> end tick from an *_expired table (empty if absent)."""
    if df is None or df.empty or "entityid" not in df.columns or "tick" not in df.columns:
        return {}
    return {int(eid): int(t) for eid, t in zip(df["entityid"], df["tick"])}


def _real_duration(kind: str, land_tick: int, entityid, end_by_id: dict[int, int]) -> int:
    """Real effect lifetime in ticks when a sane end match exists, else 0."""
    if entityid is None or entityid not in end_by_id:
        return 0
    end = end_by_id[int(entityid)]
    secs = (end - land_tick) / TICK_RATE
    lo, hi = UTILITY_DURATION_WINDOW.get(kind, (0.0, 1e9))
    if lo <= secs <= hi:
        return int(end - land_tick)
    return 0  # entityid reuse across rounds / unreliable match


def _reconstruct_throw(
    tl: PlayerTimeline, kind: str, land_tick: int, land_x: float, land_y: float,
    flight: dict[str, float],
) -> tuple[int, float, float]:
    """Estimate throw origin from the player's own position flight-seconds
    before impact. No grenade flight data exists in SourceTV demos, so this
    is an approximation; falls back to the landing point (no flight) on NaN.
    """
    fsec = float(flight.get(kind, 0.0))
    if fsec <= 0:
        return -1, land_x, land_y
    throw_tick = int(land_tick - fsec * TICK_RATE)
    if throw_tick < 0:
        return -1, land_x, land_y
    tx, ty = tl.position_at(throw_tick)
    if not (np.isfinite(tx) and np.isfinite(ty)):
        return -1, land_x, land_y
    return throw_tick, float(tx), float(ty)
