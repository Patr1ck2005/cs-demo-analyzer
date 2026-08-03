"""ParsedDemo: runtime container holding DemoData + event/tick DataFrames.

DemoData (pydantic) holds serializable metadata. ParsedDemo adds the large
columnar data (events, ticks) as pandas DataFrames for efficient querying.
Serialization splits the two: JSON for metadata, Parquet for DataFrames.
"""
from __future__ import annotations

import pandas as pd

from cs_analyzer.model.types import DemoData, MatchMetadata, Player, Round


class ParsedDemo:
    """Full parsed demo: typed metadata + event/tick DataFrames.

    Not a pydantic model (DataFrame isn't natively serializable). Use
    `model.io.save_parsed_demo` / `load_parsed_demo` for persistence.
    """

    def __init__(
        self,
        data: DemoData,
        events: dict[str, pd.DataFrame],
        ticks: pd.DataFrame,
    ) -> None:
        self.data = data
        self.events = events
        self.ticks = ticks

    # ---- convenience proxies to DemoData ----

    @property
    def metadata(self) -> MatchMetadata:
        return self.data.metadata

    @property
    def players(self) -> list[Player]:
        return self.data.players

    @property
    def rounds(self) -> list[Round]:
        return self.data.rounds

    @property
    def regular_rounds(self) -> list[Round]:
        return self.data.regular_rounds

    @property
    def steamids(self) -> list[str]:
        return [p.steamid for p in self.data.players]

    # ---- query helpers ----

    def player(self, steamid_or_name: str) -> Player | None:
        """Look up player by steamid or name."""
        return self.data.player_by_steamid(steamid_or_name) or self.data.player_by_name(steamid_or_name)

    def round_ticks(self, steamid: str, round_num: int) -> pd.DataFrame:
        """Tick rows for a player during a specific round (1-indexed)."""
        if not 1 <= round_num <= len(self.data.rounds):
            raise IndexError(f"round_num {round_num} out of range (1..{len(self.data.rounds)})")
        rnd = self.data.rounds[round_num - 1]
        mask = (
            (self.ticks["steamid"] == steamid)
            & (self.ticks["tick"] >= rnd.start_tick)
            & (self.ticks["tick"] <= rnd.end_tick)
        )
        return self.ticks[mask]

    def player_events(self, event_type: str, steamid: str, column: str = "attacker_steamid") -> pd.DataFrame:
        """Rows of an event type where the player is involved.

        `column` selects which steamid column to match: "attacker_steamid"
        for kills/damage dealt, "user_steamid" for damage taken, etc.
        """
        df = self.events.get(event_type)
        if df is None or column not in df.columns:
            return df.iloc[0:0] if df is not None else pd.DataFrame()
        return df[df[column] == steamid]

    def events_in_round(self, event_type: str, round_num: int) -> pd.DataFrame:
        """Rows of an event type within a round's tick range."""
        if event_type not in self.events:
            return pd.DataFrame()
        if not 1 <= round_num <= len(self.data.rounds):
            return pd.DataFrame().iloc[0:0]
        rnd = self.data.rounds[round_num - 1]
        df = self.events[event_type]
        if "tick" not in df.columns:
            return df.iloc[0:0]
        return df[(df["tick"] >= rnd.start_tick) & (df["tick"] <= rnd.end_tick)]
