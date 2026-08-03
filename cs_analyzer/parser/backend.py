"""demoparser2 wrapper: .dem -> raw DataFrames -> ParsedDemo.

Provider-agnostic. Source-specific adjustments happen in the Provider layer.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from demoparser2 import DemoParser

from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import (
    DemoData,
    MatchMetadata,
    Player,
    ProviderKind,
    Round,
    Team,
)

logger = logging.getLogger(__name__)

# Event types we always try to parse. Missing ones are silently skipped.
WANTED_EVENT_TYPES: tuple[str, ...] = (
    "round_start",
    "round_end",
    "round_mvp",
    "begin_new_match",
    "player_hurt",
    "player_death",
    "weapon_fire",
    "player_spawn",
    "player_team",
    "player_blind",
    "bomb_planted",
    "bomb_defused",
    "bomb_exploded",
    "item_purchase",
    "item_pickup",
    "hegrenade_detonate",
    "flashbang_detonate",
    "smokegrenade_detonate",
    "molotov_detonate",
    "inferno_startburn",
)

# Player fields appended to every event (prefixed attacker_/user_/etc. by demoparser)
EVENT_PLAYER_FIELDS: tuple[str, ...] = (
    "X", "Y", "Z",
    "pitch", "yaw",
    "team_name", "team_num",
    "last_place_name",
    "health", "armor",
)

# Game-state fields appended via `other=`
EVENT_OTHER_FIELDS: tuple[str, ...] = (
    "total_rounds_played",
    "is_warmup_period",
    "is_freeze_period",
    "game_phase",
)


class DemoParserBackend:
    """Low-level demoparser2 wrapper producing a ParsedDemo."""

    def __init__(self, tick_fields: list[str]) -> None:
        self.tick_fields = list(tick_fields)

    # ---- public API ----

    def parse(self, dem_path: Path, demo_hash: str) -> ParsedDemo:
        """Full parse: header + player info + events + ticks."""
        dem_path = Path(dem_path)
        parser = DemoParser(str(dem_path))

        header = parser.parse_header()
        player_info = parser.parse_player_info()
        events = self._parse_events(parser)
        ticks = self._parse_ticks(parser)

        data = self._build_demo_data(dem_path, demo_hash, header, player_info, events)

        return ParsedDemo(data=data, events=events, ticks=ticks)

    def read_header(self, dem_path: Path) -> dict:
        """Quick header read for provider detection (no full parse)."""
        return DemoParser(str(dem_path)).parse_header()

    # ---- internals ----

    def _parse_events(self, parser: DemoParser) -> dict[str, pd.DataFrame]:
        available = set(parser.list_game_events())
        wanted = [e for e in WANTED_EVENT_TYPES if e in available]

        events: dict[str, pd.DataFrame] = {}
        for event_type in wanted:
            try:
                df = parser.parse_event(
                    event_type,
                    player=list(EVENT_PLAYER_FIELDS),
                    other=list(EVENT_OTHER_FIELDS),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("parse_event(%s) failed: %s", event_type, exc)
                continue
            if df is not None and not df.empty:
                # Normalize steamid columns to string for consistent comparison
                for col in df.columns:
                    if col.endswith("steamid"):
                        df[col] = df[col].astype(str)
                events[event_type] = df
        return events

    def _parse_ticks(self, parser: DemoParser) -> pd.DataFrame:
        try:
            ticks = parser.parse_ticks(self.tick_fields)
        except Exception as exc:  # noqa: BLE001
            logger.warning("parse_ticks failed: %s", exc)
            return pd.DataFrame()
        # Normalize steamid to string for consistent comparison with Player model
        if "steamid" in ticks.columns and not ticks.empty:
            ticks["steamid"] = ticks["steamid"].astype(str)
        return ticks

    def _build_demo_data(
        self,
        dem_path: Path,
        demo_hash: str,
        header: dict,
        player_info: pd.DataFrame,
        events: dict[str, pd.DataFrame],
    ) -> DemoData:
        map_name = str(header.get("map_name", "unknown"))
        server_name = header.get("server_name")
        client_name = header.get("client_name")

        players = self._build_players(player_info)
        rounds = self._build_rounds(events, players)
        team_a, team_b = self._build_teams(player_info)

        metadata = MatchMetadata(
            map_name=map_name,
            demo_path=str(dem_path),
            demo_hash=demo_hash,
            provider=ProviderKind.UNKNOWN,  # set by provider layer
            server_name=server_name,
            client_name=client_name,
            tick_rate=64,
            demo_duration_ticks=int(rounds[-1].end_tick) if rounds else 0,
            team_a=team_a,
            team_b=team_b,
        )

        return DemoData(
            metadata=metadata,
            players=players,
            rounds=rounds,
        )

    def _build_players(self, player_info: pd.DataFrame) -> list[Player]:
        if player_info is None or player_info.empty:
            return []

        players: list[Player] = []
        seen: set[str] = set()
        for _, row in player_info.iterrows():
            steamid = str(row.get("steamid", ""))
            if not steamid or steamid in seen:
                continue
            seen.add(steamid)
            team_num = int(row.get("team_number", 0))
            # CS2 team numbers: 2 = T, 3 = CT (0/1 = spectator/gfx)
            team_name = f"Team {team_num}" if team_num in (2, 3) else f"Team {team_num}"
            players.append(
                Player(
                    steamid=steamid,
                    name=str(row.get("name", "")),
                    team=team_name,
                )
            )
        return players

    def _build_teams(self, player_info: pd.DataFrame) -> tuple[Team, Team]:
        """Build two Team objects, inferring starting side from team_number.

        CS2: team_number 2 = T (terrorists), 3 = CT (counter-terrorists).
        team_a is always the CT-starting team, team_b the T-starting team,
        so downstream side-swap logic stays consistent.
        """
        if player_info is None or player_info.empty:
            return (
                Team(name="Team A", starting_side="CT"),
                Team(name="Team B", starting_side="T"),
            )

        has_ct = any(int(r.get("team_number", 0)) == 3 for _, r in player_info.iterrows())
        has_t = any(int(r.get("team_number", 0)) == 2 for _, r in player_info.iterrows())

        ct_name = "Team 3" if has_ct else "Team A"
        t_name = "Team 2" if has_t else "Team B"

        return (
            Team(name=ct_name, starting_side="CT"),
            Team(name=t_name, starting_side="T"),
        )

    def _build_rounds(self, events: dict[str, pd.DataFrame], players: list[Player]) -> list[Round]:
        round_starts = events.get("round_start")
        round_ends = events.get("round_end")

        if round_ends is None or round_ends.empty:
            return []

        rounds: list[Round] = []
        # round_end has: tick, winner, reason, message, + other fields
        ends = round_ends.sort_values("tick").reset_index(drop=True)

        # Match start tick from begin_new_match
        begin_new_match = events.get("begin_new_match")
        match_start_tick = 0
        if begin_new_match is not None and not begin_new_match.empty:
            match_start_tick = int(begin_new_match["tick"].iloc[0])

        # Compute round start ticks: first round starts at match_start, subsequent
        # rounds start right after the previous round_end tick.
        start_ticks: list[int] = []
        prev_end = match_start_tick
        for _, end_row in ends.iterrows():
            start_ticks.append(prev_end)
            prev_end = int(end_row["tick"])

        t_score = 0
        ct_score = 0
        for i, (_, end_row) in enumerate(ends.iterrows()):
            end_tick = int(end_row["tick"])
            start_tick = start_ticks[i]
            winner_side = self._winner_side(end_row)

            if winner_side == "T":
                t_score += 1
            elif winner_side == "CT":
                ct_score += 1

            bomb_site = self._bomb_site_for_round(events, start_tick, end_tick)

            is_warmup = bool(end_row.get("is_warmup_period", False)) if "is_warmup_period" in end_row else False

            rounds.append(
                Round(
                    number=i + 1,
                    start_tick=start_tick,
                    end_tick=end_tick,
                    duration_ticks=end_tick - start_tick,
                    winner="",  # team name filled by provider if available
                    winner_side=winner_side,
                    bomb_planted=bomb_site is not None,
                    bomb_site=bomb_site,
                    t_score=t_score,
                    ct_score=ct_score,
                    is_warmup=is_warmup,
                )
            )

        return rounds

    def _winner_side(self, round_end_row: pd.Series) -> str:
        """Extract winner side from round_end event.

        CS2 winner enum: 2 = T (terrorists), 3 = CT (counter-terrorists).
        (CS:GO used 1=T, 2=CT; CS2 shifted to 2/3.)
        """
        if "winner" in round_end_row:
            try:
                winner = int(round_end_row["winner"])
            except (ValueError, TypeError):
                return ""
            return {2: "T", 3: "CT"}.get(winner, "")
        return ""

    def _bomb_site_for_round(
        self, events: dict[str, pd.DataFrame], start_tick: int, end_tick: int
    ) -> str | None:
        bomb = events.get("bomb_planted")
        if bomb is None or bomb.empty:
            return None
        in_round = (bomb["tick"] >= start_tick) & (bomb["tick"] <= end_tick)
        if not in_round.any():
            return None
        # last_place_name gives "BombsiteA" / "BombsiteB"
        col = "user_last_place_name" if "user_last_place_name" in bomb.columns else None
        if col is None:
            return None
        place = bomb.loc[in_round, col].iloc[0]
        if isinstance(place, str):
            if "A" in place:
                return "A"
            if "B" in place:
                return "B"
        return None

