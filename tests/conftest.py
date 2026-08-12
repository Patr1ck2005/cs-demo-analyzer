"""Shared fixtures for CsDemoAnalyzer tests.

Tests avoid parsing the 60MB real demo where possible by constructing
synthetic ParsedDemo objects. The real demo is parsed once per session
(session-scoped fixture) for end-to-end / regression checks.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import (
    DemoData,
    MatchMetadata,
    Player,
    ProviderKind,
    Round,
    Team,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_DEMO = REPO_ROOT / "tutorial/demoparser/src/parser/test_demo.dem"

# SteamIDs used across synthetic fixtures (64-bit, string-typed)
S_ALICE = "76561111111110001"  # Team 3 (CT-starting)
S_BOB = "76561111111110002"
S_CAROL = "76561111111110003"  # Team 2 (T-starting)
S_DAVE = "76561111111110004"


def make_team(name: str, starting_side: str) -> Team:
    return Team(name=name, starting_side=starting_side)


def make_player(steamid: str, name: str, team: str) -> Player:
    return Player(steamid=steamid, name=name, team=team)


def make_round(
    number: int,
    start: int,
    end: int,
    winner_side: str,
    winner: str = "",
    t_score: int = 0,
    ct_score: int = 0,
    is_warmup: bool = False,
) -> Round:
    return Round(
        number=number,
        start_tick=start,
        end_tick=end,
        duration_ticks=end - start,
        winner=winner,
        winner_side=winner_side,
        t_score=t_score,
        ct_score=ct_score,
        is_warmup=is_warmup,
    )


def build_demo_data() -> DemoData:
    """Two-round demo with 4 players (2 per team)."""
    team_a = make_team("Team 3", "CT")  # Alice, Bob
    team_b = make_team("Team 2", "T")  # Carol, Dave
    players = [
        make_player(S_ALICE, "Alice", "Team 3"),
        make_player(S_BOB, "Bob", "Team 3"),
        make_player(S_CAROL, "Carol", "Team 2"),
        make_player(S_DAVE, "Dave", "Team 2"),
    ]
    rounds = [
        make_round(1, 0, 2560, "CT", winner="Team 3", ct_score=1),
        make_round(2, 2560, 5120, "T", winner="Team 2", ct_score=1, t_score=1),
    ]
    metadata = MatchMetadata(
        map_name="de_mirage",
        demo_path="synthetic.dem",
        demo_hash="abc123",
        provider=ProviderKind.UNKNOWN,
        team_a=team_a,
        team_b=team_b,
    )
    return DemoData(metadata=metadata, players=players, rounds=rounds)


def build_parsed_demo(
    events: dict[str, pd.DataFrame] | None = None,
    ticks: pd.DataFrame | None = None,
) -> ParsedDemo:
    return ParsedDemo(
        data=build_demo_data(),
        events=events or {},
        ticks=ticks if ticks is not None else pd.DataFrame(),
    )


@pytest.fixture
def demo_data() -> DemoData:
    return build_demo_data()


@pytest.fixture
def parsed_demo() -> ParsedDemo:
    return build_parsed_demo()


@pytest.fixture(scope="session")
def real_demo_path() -> Path:
    if not REAL_DEMO.exists():
        pytest.skip(f"real demo not present: {REAL_DEMO}")
    return REAL_DEMO
