"""Tests for the parser layer: player/round building, provider detection, cache."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.cache import DemoCache
from cs_analyzer.model.types import ProviderKind
from cs_analyzer.parser.backend import DemoParserBackend
from cs_analyzer.parser.providers import (
    DEFAULT_PROVIDER_CHAIN,
    detect_provider,
)

from .conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE, make_round


def test_build_players_team_mapping() -> None:
    player_info = pd.DataFrame(
        {
            "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE],
            "name": ["Alice", "Bob", "Carol", "Dave"],
            "team_number": [3, 3, 2, 2],
        }
    )
    players = DemoParserBackend(tick_fields=[])._build_players(player_info)
    teams = {p.name: p.team for p in players}
    assert teams == {"Alice": "Team 3", "Bob": "Team 3", "Carol": "Team 2", "Dave": "Team 2"}


def test_build_players_dedupes_steamids() -> None:
    player_info = pd.DataFrame(
        {
            "steamid": [S_ALICE, S_ALICE, S_BOB],
            "name": ["Alice", "Alice2", "Bob"],
            "team_number": [3, 3, 3],
        }
    )
    players = DemoParserBackend(tick_fields=[])._build_players(player_info)
    assert len(players) == 2


def test_build_players_empty() -> None:
    players = DemoParserBackend(tick_fields=[])._build_players(pd.DataFrame())
    assert players == []


def test_winner_side_mapping() -> None:
    backend = DemoParserBackend(tick_fields=[])
    assert backend._winner_side(pd.Series({"winner": 2})) == "T"
    assert backend._winner_side(pd.Series({"winner": 3})) == "CT"
    assert backend._winner_side(pd.Series({"winner": 0})) == ""
    assert backend._winner_side(pd.Series({})) == ""


def test_build_rounds_scores_and_duration() -> None:
    round_start = pd.DataFrame({"tick": [0, 2560]})
    round_end = pd.DataFrame(
        {"tick": [2560, 5120], "winner": [2, 3], "is_warmup_period": [False, False]}
    )
    rounds = DemoParserBackend(tick_fields=[])._build_rounds(
        {"round_start": round_start, "round_end": round_end}, []
    )
    assert len(rounds) == 2
    r1, r2 = rounds
    assert (r1.start_tick, r1.end_tick) == (0, 2560)
    assert (r2.start_tick, r2.end_tick) == (2560, 5120)
    assert r1.duration_ticks == 2560
    assert r1.winner_side == "T"
    assert r2.winner_side == "CT"
    assert r1.t_score == 1 and r1.ct_score == 0
    assert r2.t_score == 1 and r2.ct_score == 1


def test_build_rounds_empty_when_no_round_end() -> None:
    rounds = DemoParserBackend(tick_fields=[])._build_rounds({}, [])
    assert rounds == []


def test_provider_detection_valve() -> None:
    header = {"server_name": "Valve Counter-Strike 2 helsinki Server", "client_name": "SourceTV Demo"}
    provider = detect_provider(header, DEFAULT_PROVIDER_CHAIN)
    assert provider.kind() == ProviderKind.VALVE


def test_provider_detection_faceit() -> None:
    header = {"server_name": "FACEIT CS2 UK", "client_name": ""}
    provider = detect_provider(header, DEFAULT_PROVIDER_CHAIN)
    assert provider.kind() == ProviderKind.FACEIT


def test_provider_detection_perfect_world() -> None:
    header = {"server_name": "perfect world", "client_name": ""}
    assert detect_provider(header, DEFAULT_PROVIDER_CHAIN).kind() == ProviderKind.PERFECT_WORLD
    header2 = {"server_name": "5eplay", "client_name": ""}
    assert detect_provider(header2, DEFAULT_PROVIDER_CHAIN).kind() == ProviderKind.PERFECT_WORLD


def test_provider_detection_fallback_valve() -> None:
    header = {"server_name": "some random server", "client_name": ""}
    assert detect_provider(header, DEFAULT_PROVIDER_CHAIN).kind() == ProviderKind.VALVE


def test_round_winner_team_name_fill(real_demo_path) -> None:
    """Provider normalize fills round.winner from winner_side."""
    from cs_analyzer.model.parsed_demo import ParsedDemo
    from cs_analyzer.model.types import DemoData, MatchMetadata, ProviderKind, Team
    from cs_analyzer.parser.providers import ValveProvider

    team_a = Team(name="NAVI", starting_side="CT")
    team_b = Team(name="G2", starting_side="T")
    rounds = [
        make_round(1, 0, 2560, "CT"),
        make_round(2, 2560, 5120, "T"),
    ]
    meta = MatchMetadata(
        map_name="de_mirage", demo_path="x", demo_hash="x",
        provider=ProviderKind.UNKNOWN, team_a=team_a, team_b=team_b,
    )
    demo = ParsedDemo(data=DemoData(metadata=meta, players=[], rounds=rounds), events={}, ticks=pd.DataFrame())

    ValveProvider().normalize(demo)
    assert demo.data.rounds[0].winner == "NAVI"
    assert demo.data.rounds[1].winner == "G2"


def test_cache_hash_sha256(real_demo_path, tmp_path) -> None:
    cache = DemoCache(tmp_path)
    digest = cache.hash_demo(real_demo_path)
    assert len(digest) == 64
    assert digest.isalnum()
    # deterministic
    assert cache.hash_demo(real_demo_path) == digest
    # matches the pre-existing cache entry (content-addressed)
    assert digest == "84a1a4191302bdd2a3bbb5a727842093744b1fb1a228aeec630369e44b622cb2"


def test_cache_save_load_roundtrip(parsed_demo, tmp_path) -> None:
    cache = DemoCache(tmp_path)
    cache.save("cafebabe", parsed_demo)
    assert cache.exists("cafebabe")
    reloaded = cache.load("cafebabe")
    assert reloaded is not None
    assert reloaded.data == parsed_demo.data
