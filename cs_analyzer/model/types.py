"""Pydantic models for demo metadata, players, and rounds.

These are the JSON-serializable parts of the parsed demo. Event and tick
data (large, columnar) live in DataFrames on ParsedDemo, serialized to Parquet.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ProviderKind(str, Enum):
    """Source platform of the demo. All use Valve demo format; differ in metadata."""

    VALVE = "valve"
    FACEIT = "faceit"
    ESEA = "esea"
    FIVEE = "5eplay"
    PERFECT_WORLD = "perfect_world"
    UNKNOWN = "unknown"


class Team(BaseModel):
    name: str  # "Team X" or clan name
    clan_name: str | None = None
    starting_side: str = "CT"  # CT or T
    score_first_half: int = 0
    score_second_half: int = 0
    score_overtime: int = 0
    score_total: int = 0


class Player(BaseModel):
    steamid: str  # 64-bit SteamID as string (preserves precision)
    name: str
    team: str  # team name at match start
    is_coach: bool = False


class Round(BaseModel):
    number: int  # 1-indexed
    start_tick: int
    end_tick: int
    duration_ticks: int
    winner: str  # team name
    winner_side: str  # "CT" or "T"
    bomb_planted: bool = False
    bomb_site: str | None = None  # "A" or "B"
    t_score: int  # cumulative T score after this round
    ct_score: int  # cumulative CT score after this round
    is_warmup: bool = False
    is_overtime: bool = False


class MatchMetadata(BaseModel):
    map_name: str
    demo_path: str
    demo_hash: str
    provider: ProviderKind
    match_id: str | None = None
    parsed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tick_rate: int = 64
    demo_duration_ticks: int = 0
    team_a: Team
    team_b: Team
    server_name: str | None = None
    client_name: str | None = None


class DemoData(BaseModel):
    """Static, JSON-serializable representation of a parsed demo."""

    metadata: MatchMetadata
    players: list[Player]
    rounds: list[Round]
    schema_version: str = "1.0.0"

    @property
    def regular_rounds(self) -> list[Round]:
        """Rounds excluding warmup."""
        return [r for r in self.rounds if not r.is_warmup]

    def player_by_steamid(self, steamid: str) -> Player | None:
        for p in self.players:
            if p.steamid == steamid:
                return p
        return None

    def player_by_name(self, name: str) -> Player | None:
        for p in self.players:
            if p.name == name:
                return p
        return None

    def round_at_tick(self, tick: int) -> Round | None:
        for r in self.rounds:
            if r.start_tick <= tick <= r.end_tick:
                return r
        return None
