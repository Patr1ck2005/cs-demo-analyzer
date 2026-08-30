"""demoparser2 wrapper: .dem -> raw DataFrames -> ParsedDemo.

Provider-agnostic. Source-specific adjustments happen in the Provider layer.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
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
    "round_freeze_end",
    "round_end",
    "round_mvp",
    "begin_new_match",
    "player_hurt",
    "player_death",
    "weapon_fire",
    "player_jump",
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
    "smokegrenade_expired",
    "inferno_expire",
    "weapon_reload",
    # Phase I (probed 2026-08-25, output/.event_probe.json): bomb lifecycle
    # + zoom available on WMPVP broadcasts; bullet_impact / *_thrown are
    # ABSENT there (empty list) but stay listed so Valve/FACEIT demos get
    # them for free — the try/except below skips missing types silently.
    "bomb_begindefuse",   # carries `haskit`
    "bomb_abortdefuse",
    "bomb_dropped",
    "bomb_pickup",
    "weapon_zoom",
    "cs_win_panel_match",
    "bullet_impact",
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

        data = self._build_demo_data(dem_path, demo_hash, header, player_info, events, ticks)

        return ParsedDemo(data=data, events=events, ticks=ticks)

    def read_header(self, dem_path: Path) -> dict:
        """Quick header read for provider detection (no full parse)."""
        return DemoParser(str(dem_path)).parse_header()

    # ---- internals ----

    def _parse_events(self, parser: DemoParser) -> dict[str, pd.DataFrame]:
        # Do NOT pre-filter with list_game_events(): some demos (e.g. WMPVP
        # SourceTV broadcasts) omit round_start/round_end from that list even
        # though parse_event() returns them. Try every wanted type, skip failures.
        events: dict[str, pd.DataFrame] = {}
        for event_type in WANTED_EVENT_TYPES:
            try:
                df = parser.parse_event(
                    event_type,
                    player=list(EVENT_PLAYER_FIELDS),
                    other=list(EVENT_OTHER_FIELDS),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("parse_event(%s) failed: %s", event_type, exc)
                continue
            if not isinstance(df, pd.DataFrame):
                logger.debug("parse_event(%s) returned non-DataFrame (%s); skipping", event_type, type(df).__name__)
                continue
            if not df.empty:
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
            # Retry with the legacy field list: a future demoparser2 may drop
            # or half-materialize the newer props (active_weapon_ammo /
            # is_in_reload / inventory). Degrade gracefully instead of
            # losing all ticks.
            dropped = ("active_weapon_ammo", "is_in_reload", "inventory")
            legacy = [f for f in self.tick_fields if f not in dropped]
            if legacy == self.tick_fields:
                logger.warning("parse_ticks failed: %s", exc)
                return pd.DataFrame()
            logger.warning("parse_ticks with new fields failed (%s); retrying legacy list", exc)
            try:
                ticks = parser.parse_ticks(legacy)
            except Exception as exc2:  # noqa: BLE001
                logger.warning("parse_ticks legacy retry failed: %s", exc2)
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
        ticks: pd.DataFrame | None = None,
    ) -> DemoData:
        map_name = str(header.get("map_name", "unknown"))
        server_name = header.get("server_name")
        client_name = header.get("client_name")

        players = self._build_players(player_info, events, ticks)
        rounds = self._build_rounds(events, players)
        team_a, team_b = self._build_teams(players)

        metadata = MatchMetadata(
            map_name=map_name,
            demo_path=str(dem_path),
            demo_hash=demo_hash,
            provider=ProviderKind.UNKNOWN,  # set by provider layer
            server_name=server_name,
            client_name=client_name,
            # Header carries no tickrate (verified: parse_header() keys are
            # version/map/server only) — derive from movement samples instead.
            tick_rate=self._empirical_tick_rate(ticks) or 64,
            demo_duration_ticks=int(rounds[-1].end_tick) if rounds else 0,
            # CS2 headers also carry no match id; the WMPVP downloader names
            # files "<matchid>_0.dem" so lift it from the filename when present.
            match_id=self._match_id_from_filename(dem_path),
            team_a=team_a,
            team_b=team_b,
        )

        return DemoData(
            metadata=metadata,
            players=players,
            rounds=rounds,
        )

    @staticmethod
    def _empirical_tick_rate(ticks: pd.DataFrame | None) -> int | None:
        """Derive the demo tick rate from movement samples.

        speed (units/s, `velocity`) divided by per-tick displacement equals
        ticks per second. Probed on real WMPVP demos: median 64.0 over 116k
        moving samples. Returns None when evidence is insufficient.
        """
        if ticks is None or ticks.empty:
            return None
        needed = {"steamid", "tick", "X", "Y", "velocity"}
        if not needed.issubset(ticks.columns):
            return None
        t = ticks[["steamid", "tick", "X", "Y", "velocity"]].sort_values(["steamid", "tick"])
        dx = t.groupby("steamid")["X"].diff().abs()
        dy = t.groupby("steamid")["Y"].diff().abs()
        disp = np.hypot(dx, dy)
        v = t["velocity"]
        mask = (disp > 1) & (disp < 20) & (v > 50)
        ratio = (v[mask] / disp[mask]).replace([np.inf, -np.inf], np.nan).dropna()
        if len(ratio) < 100:
            return None
        median = float(ratio.median())
        # Snap to the nearest standard CS2 tick rate.
        return int(min((32, 64, 128), key=lambda r: abs(r - median)))

    # platform match-id shapes found in filenames:
    #   WMPVP: "9206943388297116556_0.dem"
    #   5E:    "g161-20260828233826747829917_de_cache.dem" (digits embed date)
    _MATCH_ID_PATTERNS = (
        re.compile(r"^(\d{10,})_"),
        re.compile(r"^g161-(\d{15,})_"),
    )

    @classmethod
    def _match_id_from_filename(cls, dem_path: Path) -> str | None:
        """Extract a platform match id from the demo filename (Phase K3)."""
        name = Path(dem_path).name
        for pat in cls._MATCH_ID_PATTERNS:
            m = pat.match(name)
            if m:
                return m.group(1)
        return None

    def _build_players(
        self,
        player_info: pd.DataFrame,
        events: dict[str, pd.DataFrame] | None = None,
        ticks: pd.DataFrame | None = None,
    ) -> list[Player]:
        # Regulation-round boundaries: warmup/knife-phase spawns happen BEFORE
        # the first round_start and must never define a player's team.
        cutoff = self._regulation_start_tick(events)
        half_end = self._first_half_end_tick(events, cutoff)
        if player_info is not None and not player_info.empty:
            players = self._players_from_player_info(player_info)
            if players:
                # WMPVP player_info tables have been observed with stale/swapped
                # team_number columns; live per-tick team_num is ground truth.
                self._apply_live_majority(players, ticks, cutoff, half_end)
                return players
        # Fallback: some demos (WMPVP SourceTV) ship no player-info table, so
        # reconstruct the roster from player_spawn events instead.
        spawns = (events or {}).get("player_spawn")
        if spawns is not None and not spawns.empty:
            players = self._players_from_spawns(spawns, min_tick=cutoff)
            self._apply_live_majority(players, ticks, cutoff, half_end)
            self._fill_teams_from_deaths(players, events)
            return players
        return []

    @staticmethod
    def _regulation_start_tick(events: dict[str, pd.DataFrame] | None) -> int | None:
        """Tick of the first round_start (warmup happens strictly before it)."""
        rs = (events or {}).get("round_start")
        if rs is None or rs.empty or "tick" not in rs.columns:
            return None
        t = rs["tick"].dropna()
        return int(t.min()) if not t.empty else None

    @staticmethod
    def _first_half_end_tick(events: dict[str, pd.DataFrame] | None, fallback: int | None) -> int | None:
        """End tick of regulation round 12 (halftime side swap happens after).

        Falls back to the last known round_end when fewer rounds exist, then to
        `fallback` (first regulation start) so at least round 1 is covered.
        """
        re_ = (events or {}).get("round_end")
        if re_ is None or re_.empty or "tick" not in re_.columns:
            return fallback
        ends = re_["tick"].dropna().sort_values()
        if ends.empty:
            return fallback
        return int(ends.iloc[11]) if len(ends) >= 12 else int(ends.iloc[-1])

    def _majority_team(
        self, ticks: pd.DataFrame | None, steamid: str, start_tick: int | None, end_tick: int | None
    ) -> int | None:
        """Majority live team_num for a player over regulation first-half ticks.

        Returns 2 (T) / 3 (CT), or None when there is insufficient evidence
        (<50 rows). This is ground truth: it tracks halftime swaps by design.
        """
        if ticks is None or ticks.empty or "team_num" not in ticks.columns:
            return None
        sub = ticks[ticks["steamid"] == steamid]
        if start_tick is not None:
            sub = sub[sub["tick"] >= start_tick]
        if end_tick is not None:
            sub = sub[sub["tick"] <= end_tick]
        sub = sub[sub["team_num"].isin((2.0, 3.0))]
        if len(sub) < 50:
            return None
        counts = sub["team_num"].value_counts()
        if len(counts) > 1 and counts.iloc[0] == counts.iloc[1]:
            return int(sub["team_num"].iloc[0])  # tie -> earliest observation
        return int(counts.index[0])

    def _apply_live_majority(
        self,
        players: list[Player],
        ticks: pd.DataFrame | None,
        start_tick: int | None,
        end_tick: int | None,
    ) -> None:
        """Override roster teams with the live per-tick team_num majority.

        Ground truth on every provider: spawn snapshots AND player_info tables
        have both been observed stale/swapped (WMPVP SourceTV), while per-tick
        team_num tracks reality (verified against official spawn geography).
        """
        if ticks is None or ticks.empty:
            return
        for p in players:
            maj = self._majority_team(ticks, p.steamid, start_tick, end_tick)
            if maj is None:
                continue
            live_team = f"Team {maj}"
            if p.team != live_team:
                logger.warning(
                    "roster: %s snapshot said %s but live ticks say %s; trusting ticks",
                    p.steamid, p.team, live_team,
                )
                p.team = live_team

    @staticmethod
    def _players_from_player_info(player_info: pd.DataFrame) -> list[Player]:
        players: list[Player] = []
        seen: set[str] = set()
        for _, row in player_info.iterrows():
            steamid = str(row.get("steamid", ""))
            if not steamid or steamid in seen:
                continue
            seen.add(steamid)
            team_num = int(row.get("team_number", 0))
            # CS2 team numbers: 2 = T, 3 = CT (0/1 = spectator/gfx)
            players.append(
                Player(
                    steamid=steamid,
                    name=str(row.get("name", "")),
                    team=f"Team {team_num}",
                )
            )
        return players

    @staticmethod
    def _players_from_spawns(spawns: pd.DataFrame, min_tick: int | None = None) -> list[Player]:
        if "user_steamid" not in spawns.columns:
            return []
        valid = spawns[spawns["user_steamid"].notna()]
        if valid.empty:
            return []
        valid = valid[valid["user_steamid"].astype(str).str.strip() != ""]
        if valid.empty:
            return []
        # Warmup/knife-phase spawns precede the first regulation round and must
        # not decide anyone's team; prefer post-cutoff rows when available.
        if min_tick is not None and "tick" in valid.columns:
            in_round = valid[valid["tick"] >= min_tick]
            if not in_round.empty:
                valid = in_round

        players: list[Player] = []
        for steamid in valid["user_steamid"].unique():
            rows = valid[valid["user_steamid"] == steamid].sort_values("tick")
            # Prefer a spawn row where the player is on a real team (2=T, 3=CT);
            # the first spawn may be a pre-match spectator state (team 0).
            team_rows = rows[rows.get("user_team_num", pd.Series(dtype=float)).isin((2, 3))]
            chosen = team_rows.iloc[0] if not team_rows.empty else rows.iloc[0]
            team_num = chosen.get("user_team_num")
            try:
                team_num = int(team_num) if pd.notna(team_num) else 0
            except (TypeError, ValueError):
                team_num = 0
            players.append(
                Player(
                    steamid=str(steamid),
                    name=str(chosen.get("user_name", "")),
                    team=f"Team {team_num}",
                )
            )
        return players

    @staticmethod
    def _fill_teams_from_deaths(
        players: list[Player], events: dict[str, pd.DataFrame] | None
    ) -> None:
        """Assign teams to players whose spawn rows carry no team (team 0).

        Some SourceTV demos omit team_num on certain players' spawn events; the
        same players may still carry TERRORIST/CT team names in player_death /
        player_hurt rows. Players never found there stay "Team 0" (RWS=0).
        """
        tables = [(events or {}).get("player_death"), (events or {}).get("player_hurt")]
        team_of: dict[str, str] = {}
        for table in tables:
            if table is None or table.empty:
                continue
            for _, row in table.iterrows():
                for sid_col, team_col in (
                    ("attacker_steamid", "attacker_team_name"),
                    ("user_steamid", "user_team_name"),
                ):
                    if sid_col not in row or team_col not in row:
                        continue
                    sid = row[sid_col]
                    team = row[team_col]
                    if pd.isna(sid) or pd.isna(team) or not isinstance(team, str):
                        continue
                    resolved = {"TERRORIST": "Team 2", "CT": "Team 3"}.get(team.strip().upper())
                    if resolved:
                        team_of.setdefault(str(sid), resolved)
        for p in players:
            if p.team not in ("Team 2", "Team 3"):
                resolved = team_of.get(p.steamid)
                if resolved:
                    p.team = resolved

    def _build_teams(self, players: list[Player]) -> tuple[Team, Team]:
        """Build two Team objects from the player roster.

        CS2 team_number 2 = T (terrorists), 3 = CT (counter-terrorists).
        team_a is always the CT-starting team, team_b the T-starting team,
        so downstream side-swap logic stays consistent.
        """
        if not players:
            return (
                Team(name="Team A", starting_side="CT"),
                Team(name="Team B", starting_side="T"),
            )
        ct_name = next((p.team for p in players if p.team == "Team 3"), None)
        t_name = next((p.team for p in players if p.team == "Team 2"), None)
        return (
            Team(name=ct_name or "Team A", starting_side="CT"),
            Team(name=t_name or "Team B", starting_side="T"),
        )

    def _build_rounds(self, events: dict[str, pd.DataFrame], players: list[Player]) -> list[Round]:
        round_ends = events.get("round_end")
        if round_ends is None or round_ends.empty:
            return []

        # round_end has: tick, winner, reason, round, + other fields
        ends = round_ends.sort_values("tick").reset_index(drop=True)

        # Exact round-start ticks keyed by round number when round_start events
        # are present (their `round` field maps 1:1 to round_end's).
        # Warmup restarts reuse round numbers (round_start@43 round=1 warmup,
        # then the real round_start@... also round=1 after begin_new_match),
        # so a warmup start must never claim the slot from the real one:
        # non-warmup starts win per round number, warmup only fills gaps.
        starts_by_round: dict[int, int] = {}
        warmup_starts: dict[int, int] = {}
        round_starts = events.get("round_start")
        if round_starts is not None and not round_starts.empty and "tick" in round_starts.columns:
            for _, row in round_starts.iterrows():
                try:
                    rn = int(row.get("round", 0))
                except (TypeError, ValueError):
                    continue
                if rn <= 0:
                    continue
                warmup = (
                    bool(row.get("is_warmup_period", False))
                    if "is_warmup_period" in row.index
                    else False
                )
                target = warmup_starts if warmup else starts_by_round
                target.setdefault(rn, int(row["tick"]))
        for rn, tick in warmup_starts.items():
            starts_by_round.setdefault(rn, tick)

        # Fallback match-start tick (used when round_start is absent).
        begin_new_match = events.get("begin_new_match")
        match_start_tick = 0
        if begin_new_match is not None and not begin_new_match.empty:
            match_start_tick = int(begin_new_match["tick"].iloc[0])

        rounds: list[Round] = []
        prev_end = match_start_tick
        t_score = 0
        ct_score = 0
        n_real = 0
        for _, end_row in ends.iterrows():
            # Warmup pseudo-rounds (round_end fires while is_warmup_period is
            # set, sometimes with round=0 / NaN winner) never form a round of
            # their own — emitting them produced spans like 8839..43 and let
            # the warmup round_start pollute real round 1's start tick.
            if "is_warmup_period" in end_row.index and bool(end_row["is_warmup_period"]):
                continue
            n_real += 1
            end_tick = int(end_row["tick"])
            raw_num = end_row.get("round", n_real) if "round" in end_row.index else n_real
            try:
                round_num = int(raw_num)
            except (TypeError, ValueError):
                round_num = n_real
            if round_num <= 0:
                round_num = n_real
            start_tick = starts_by_round.get(round_num, prev_end)
            winner_side = self._winner_side(end_row)

            if winner_side == "T":
                t_score += 1
            elif winner_side == "CT":
                ct_score += 1

            bomb_site = self._bomb_site_for_round(events, start_tick, end_tick)

            is_warmup = bool(end_row.get("is_warmup_period", False)) if "is_warmup_period" in end_row else False

            rounds.append(
                Round(
                    number=round_num,
                    start_tick=start_tick,
                    end_tick=end_tick,
                    duration_ticks=max(end_tick - start_tick, 0),
                    winner="",  # team name filled by provider if available
                    winner_side=winner_side,
                    bomb_planted=bomb_site is not None,
                    bomb_site=bomb_site,
                    t_score=t_score,
                    ct_score=ct_score,
                    is_warmup=is_warmup,
                )
            )
            prev_end = end_tick

        return rounds

    def _winner_side(self, round_end_row: pd.Series) -> str:
        """Extract winner side from round_end event.

        Accepts both CS2 numeric enum (2 = T, 3 = CT) and the string
        form ("T"/"CT"/"TERRORIST") that some SourceTV demos expose.
        """
        if "winner" not in round_end_row:
            return ""
        winner = round_end_row["winner"]
        if isinstance(winner, str):
            w = winner.strip().upper()
            if w in ("T", "TERRORIST", "T-ERRORIST"):
                return "T"
            if w in ("CT", "COUNTER", "COUNTER-TERRORISTS"):
                return "CT"
            return ""
        try:
            winner = int(winner)
        except (ValueError, TypeError):
            return ""
        return {2: "T", 3: "CT"}.get(winner, "")

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

