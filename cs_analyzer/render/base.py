"""Renderer base class and shared data models."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from cs_analyzer.analysis.basic_stats import BasicStatsResult
from cs_analyzer.analysis.ratings import RatingsResult


class RadarPlayerData(BaseModel):
    """Per-player data formatted for the radar chart renderer.

    Mirrors the columns of the original player_statistics.csv so the
    migrated Manim scene can consume it with minimal changes.
    """

    ID: str  # player name (display)
    team: str
    KPR: float = 0.0
    Survivals: float = 0.0
    ADR: float = 0.0
    Headshot_pct: float = 0.0  # exported as "Headshot%" label
    FirstKillsPerRound: float = 0.0
    Rating_Pro: float = 0.0
    RWS: float = 0.0
    is_top: bool = False
    ranks: dict[str, int] = Field(default_factory=dict)

    def attribute_value(self, attr: str) -> float:
        """Get a player's value for an attribute, handling name aliases."""
        if attr == "Headshot%":
            return self.Headshot_pct
        if attr == "Rating Pro":
            return self.Rating_Pro
        return float(getattr(self, attr, 0.0))

    def attribute_rank(self, attr: str) -> int:
        """Rank for an attribute (1 = best). Defaults to large number if unset."""
        if attr == "Headshot%":
            return self.ranks.get("Headshot_pct", 99)
        if attr == "Rating Pro":
            return self.ranks.get("Rating_Pro", 99)
        return self.ranks.get(attr, 99)


def merge_for_radar(
    basic: BasicStatsResult,
    ratings: RatingsResult,
    attributes: list[str],
) -> list[RadarPlayerData]:
    """Merge BasicStats + Ratings into radar-ready player data, with ranks.

    Ranks are computed per attribute (1 = highest value). `is_top` is True
    if the player ranks #1 in any attribute.
    """
    players: list[RadarPlayerData] = []
    for bs in basic.players:
        rt = ratings.by_steamid(bs.steamid)
        players.append(
            RadarPlayerData(
                ID=bs.name,
                team=bs.team,
                KPR=bs.KPR,
                Survivals=bs.Survivals,
                ADR=bs.ADR,
                Headshot_pct=bs.headshot_pct,
                FirstKillsPerRound=bs.FirstKillsPerRound,
                Rating_Pro=rt.Rating_Pro if rt else 0.0,
                RWS=rt.RWS if rt else 0.0,
            )
        )

    # Compute ranks per attribute (1 = highest)
    for attr in attributes:
        sorted_players = sorted(
            players, key=lambda p: p.attribute_value(attr), reverse=True
        )
        for i, p in enumerate(sorted_players):
            rank_key = attr
            if attr == "Headshot%":
                rank_key = "Headshot_pct"
            elif attr == "Rating Pro":
                rank_key = "Rating_Pro"
            p.ranks[rank_key] = i + 1

    # is_top: player is #1 in at least one attribute
    for p in players:
        for attr in attributes:
            if p.attribute_rank(attr) == 1:
                p.is_top = True
                break

    return players


class Renderer(ABC):
    """Base class for renderers. Produces visual artifacts from analysis results."""

    @abstractmethod
    def render(self, output_path: Path) -> Path:
        """Render to output_path. Returns the path to the produced artifact."""
