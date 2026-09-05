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


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    """Temp-cached synthetic demo + monkeypatched app (cache dir & output).

    Lives in conftest so multiple test modules can share it (Phase I).
    """
    from fastapi.testclient import TestClient

    ticks = pd.DataFrame(
        {
            "tick": [0, 640, 1280, 1920, 2560, 3200],
            "steamid": [S_ALICE] * 6,
            "X": [0.0, 100.0, 200.0, 300.0, 400.0, 500.0],
            "Y": [0.0] * 6,
            "is_alive": [True] * 6,
            "team_num": [3.0] * 6,
        }
    )
    events = {
        "player_death": pd.DataFrame(
            {"tick": [1000, 2000, 3000],
             "attacker_name": ["Bob", "Alice", "Bob"],
             "user_name": ["Alice", "Bob", "Carol"],
             "attacker_steamid": [S_BOB, S_ALICE, S_BOB],
             "user_steamid": [S_ALICE, S_BOB, S_CAROL],
             "assister_steamid": ["", "", ""],
             # P5 badge columns: Alice's kill is a penetrating headshot
             "weapon": ["ak47", "usp", "knife"],
             "headshot": [False, True, False],
             "penetrated": [False, True, False],
             "thrusmoke": [False, False, False],
             "noscope": [False, False, False],
             "attackerinair": [False, False, False]}
        )
    }
    from cs_analyzer.cache import DemoCache as _DC
    from cs_analyzer.web import app as web_app

    demo = build_parsed_demo(ticks=ticks, events=events)
    demo_hash = demo.metadata.demo_hash
    cache = _DC(tmp_path / "cache")
    cache.save(demo_hash, demo)
    monkeypatch.setattr(web_app, "_cache", lambda: cache)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")
    monkeypatch.setattr(web_app, "_demos_dir", lambda: tmp_path / "demos")
    # T2: pin settings to DEFAULTS — the repo's configs/default.yaml turns
    # scan_executor on, and web tests must stay on the deterministic thread
    # path (no real process spawns per memo).
    from cs_analyzer.config import Settings as _Settings

    monkeypatch.setattr(web_app, "_settings", lambda: _Settings())
    # aggregate memo must not leak between tests (module-level singleton)
    from cs_analyzer.web import aggregation

    aggregation.invalidate_aggregate()
    return TestClient(web_app.app), demo_hash, demo


@pytest.fixture(scope="session")
def real_demo_path() -> Path:
    if not REAL_DEMO.exists():
        pytest.skip(f"real demo not present: {REAL_DEMO}")
    return REAL_DEMO
