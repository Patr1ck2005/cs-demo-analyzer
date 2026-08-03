"""Layer 2: Typed data models for parsed demos.

- DemoData: static metadata, players, rounds (pydantic, JSON-serializable)
- ParsedDemo: DemoData + event/tick DataFrames (runtime container)
- io: save/load DemoData + DataFrames to JSON + Parquet
"""
from cs_analyzer.model.types import (
    DemoData,
    MatchMetadata,
    Player,
    ProviderKind,
    Round,
    Team,
)
from cs_analyzer.model.parsed_demo import ParsedDemo

__all__ = [
    "DemoData",
    "MatchMetadata",
    "ParsedDemo",
    "Player",
    "ProviderKind",
    "Round",
    "Team",
]
