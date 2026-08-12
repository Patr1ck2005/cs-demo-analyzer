"""Tests for the parser layer: player/round building, provider detection, cache."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.cache import DemoCache
from cs_analyzer.model.types import Player, ProviderKind
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


def test_winner_side_string_values() -> None:
    backend = DemoParserBackend(tick_fields=[])
    assert backend._winner_side(pd.Series({"winner": "T"})) == "T"
    assert backend._winner_side(pd.Series({"winner": "CT"})) == "CT"
    assert backend._winner_side(pd.Series({"winner": "TERRORIST"})) == "T"
    assert backend._winner_side(pd.Series({"winner": "Counter-Terrorists"})) == "CT"
    assert backend._winner_side(pd.Series({"winner": "other"})) == ""


def test_build_players_fallback_from_spawns() -> None:
    spawns = pd.DataFrame(
        {
            "tick": [100, 100, 200],
            "user_steamid": [S_ALICE, S_BOB, S_ALICE],
            "user_name": ["Alice", "Bob", "Alice"],
            "user_team_num": [3.0, 2.0, 3.0],
        }
    )
    players = DemoParserBackend(tick_fields=[])._build_players(pd.DataFrame(), {"player_spawn": spawns})
    by_id = {p.steamid: p for p in players}
    assert len(players) == 2
    assert by_id[S_ALICE].name == "Alice"
    assert by_id[S_ALICE].team == "Team 3"
    assert by_id[S_BOB].team == "Team 2"


def test_build_players_spawn_ignores_team0_first_spawn() -> None:
    # first spawn is spectator (team 0); later spawn has a real team
    spawns = pd.DataFrame(
        {
            "tick": [100, 300],
            "user_steamid": [S_ALICE, S_ALICE],
            "user_name": ["Alice", "Alice"],
            "user_team_num": [0.0, 3.0],
        }
    )
    players = DemoParserBackend(tick_fields=[])._build_players(pd.DataFrame(), {"player_spawn": spawns})
    assert players[0].team == "Team 3"


def test_fill_teams_from_deaths() -> None:
    players = [Player(steamid=S_ALICE, name="Alice", team="Team 0")]
    deaths = pd.DataFrame(
        {
            "attacker_steamid": [S_ALICE, S_BOB],
            "attacker_team_name": ["CT", "TERRORIST"],
            "user_steamid": [S_BOB, S_ALICE],
            "user_team_name": ["TERRORIST", "CT"],
        }
    )
    DemoParserBackend(tick_fields=[])._fill_teams_from_deaths(players, {"player_death": deaths})
    assert players[0].team == "Team 3"


def test_build_rounds_uses_round_start_ticks() -> None:
    round_start = pd.DataFrame({"tick": [1000, 3000], "round": [1, 2]})
    round_end = pd.DataFrame({"tick": [2500, 5000], "winner": ["T", "CT"], "round": [1, 2]})
    rounds = DemoParserBackend(tick_fields=[])._build_rounds(
        {"round_start": round_start, "round_end": round_end}, []
    )
    assert len(rounds) == 2
    assert (rounds[0].start_tick, rounds[0].end_tick) == (1000, 2500)
    assert (rounds[1].start_tick, rounds[1].end_tick) == (3000, 5000)
    assert rounds[0].winner_side == "T"
    assert rounds[1].winner_side == "CT"


def test_parse_events_ignores_list_game_events_omission(monkeypatch) -> None:
    class FakeParser:
        def list_game_events(self):  # omits round_start/round_end
            return ["player_death"]

        def parse_event(self, event_type, player=None, other=None):
            if event_type == "round_end":
                return pd.DataFrame({"tick": [100], "winner": ["T"]})
            if event_type == "round_start":
                return pd.DataFrame({"tick": [0], "round": [1]})
            return pd.DataFrame()

    events = DemoParserBackend(tick_fields=[])._parse_events(FakeParser())
    assert "round_end" in events
    assert "round_start" in events
    assert events["round_end"].iloc[0]["winner"] == "T"


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
