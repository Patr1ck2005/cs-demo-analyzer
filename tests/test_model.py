"""Tests for the model layer: serialization roundtrips and query helpers."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.model.io import (
    EVENTS_DIRNAME,
    MODEL_FILENAME,
    TICKS_FILENAME,
    cache_key,
    load_parsed_demo,
    save_parsed_demo,
)
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import DemoData, ProviderKind

from .conftest import S_ALICE, build_demo_data


def test_demodata_json_roundtrip(demo_data: DemoData) -> None:
    dumped = demo_data.model_dump_json()
    reloaded = DemoData.model_validate_json(dumped)
    assert reloaded == demo_data
    assert reloaded.metadata.map_name == demo_data.metadata.map_name
    assert [p.steamid for p in reloaded.players] == [p.steamid for p in demo_data.players]
    assert reloaded.schema_version == "1.0.0"


def test_demodata_roundtrip_utf8_names() -> None:
    data = build_demo_data()
    data.players[0].name = "Подсосник blick'a"  # Cyrillic survives roundtrip
    reloaded = DemoData.model_validate_json(data.model_dump_json())
    assert reloaded.players[0].name == "Подсосник blick'a"


def test_regular_rounds_excludes_warmup(demo_data: DemoData) -> None:
    demo_data.rounds[0].is_warmup = True
    assert len(demo_data.regular_rounds) == 1
    assert demo_data.regular_rounds[0].number == 2


def test_player_lookup_by_steamid_and_name(demo_data: DemoData) -> None:
    assert demo_data.player_by_steamid(S_ALICE).name == "Alice"
    assert demo_data.player_by_name("Dave").steamid == "76561111111110004"
    assert demo_data.player_by_steamid("nope") is None
    assert demo_data.player_by_name("nope") is None


def test_round_at_tick(demo_data: DemoData) -> None:
    assert demo_data.round_at_tick(100).number == 1
    assert demo_data.round_at_tick(3000).number == 2
    assert demo_data.round_at_tick(-5) is None


def test_save_load_parsed_demo_roundtrip(tmp_path) -> None:
    demo = build_demo_data()
    events = {
        "player_death": pd.DataFrame(
            {
                "tick": [100],
                "attacker_steamid": [S_ALICE],
                "user_steamid": ["76561111111110004"],
            }
        ),
        "round_start": pd.DataFrame({"tick": [0, 2560]}),
    }
    ticks = pd.DataFrame(
        {"tick": [0, 128], "steamid": [S_ALICE, S_ALICE], "X": [1.0, 2.0], "Y": [3.0, 4.0]}
    )
    parsed = ParsedDemo(data=demo, events=events, ticks=ticks)

    save_parsed_demo(parsed, tmp_path)
    assert (tmp_path / MODEL_FILENAME).exists()
    assert (tmp_path / TICKS_FILENAME).exists()
    assert (tmp_path / EVENTS_DIRNAME / "player_death.parquet").exists()
    assert (tmp_path / EVENTS_DIRNAME / "round_start.parquet").exists()

    reloaded = load_parsed_demo(tmp_path)
    assert reloaded.data == demo
    assert reloaded.ticks.shape == ticks.shape
    assert set(reloaded.events.keys()) == {"player_death", "round_start"}
    assert reloaded.events["player_death"].iloc[0]["attacker_steamid"] == S_ALICE


def test_save_load_roundtrip_empty_ticks(tmp_path) -> None:
    demo = build_demo_data()
    parsed = ParsedDemo(data=demo, events={}, ticks=pd.DataFrame())
    save_parsed_demo(parsed, tmp_path)
    reloaded = load_parsed_demo(tmp_path)
    assert reloaded.data == demo
    assert reloaded.ticks.empty
    assert reloaded.events == {}


def test_cache_key_format() -> None:
    assert cache_key("deadbeef", "1.0.0") == "deadbeef_v1.0.0"
    assert cache_key("deadbeef") == "deadbeef_v1.0.0"


def test_provider_kind_is_enum_serializable(demo_data: DemoData) -> None:
    demo_data.metadata.provider = ProviderKind.FACEIT
    reloaded = DemoData.model_validate_json(demo_data.model_dump_json())
    assert reloaded.metadata.provider == ProviderKind.FACEIT
    assert isinstance(reloaded.metadata.provider, ProviderKind)
