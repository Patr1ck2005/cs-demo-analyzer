"""K5 tests: five-stack teamplay analytics (links, regulars, stack split)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from cs_analyzer.analysis.teamplay import build_teamplay_report, is_five_e
from cs_analyzer.cache import DemoCache
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import DemoData, MatchMetadata, Player, ProviderKind, Round, Team

from .conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE

S_EVE = "76561111111110005"


def _teamplay_demo(path_name: str, deaths: pd.DataFrame, roster: list[Player]) -> ParsedDemo:
    """One regular round (ticks 1000..2000) with the given player_death feed.

    Live tick sides (what round_player_sides reads): Alice/Bob = T (team 2),
    Carol/Dave = CT (team 3) — pass a custom roster for other layouts.
    """
    tick_rows = []
    for p in roster:
        team = 2.0 if p.team == "Team 2" else 3.0
        for t in (1000, 1500, 2000):
            tick_rows.append({"tick": t, "steamid": p.steamid, "team_num": team,
                              "X": 100.0, "Y": 50.0, "is_alive": True})
    rnd = Round(number=1, start_tick=1000, end_tick=2000, duration_ticks=1000,
                winner="", winner_side="T", t_score=1, ct_score=0)
    data = DemoData(
        metadata=MatchMetadata(
            map_name="de_mirage", demo_path=path_name, demo_hash="tp-" + path_name,
            provider=ProviderKind.UNKNOWN,
            team_a=Team(name="CT side", starting_side="CT"),
            team_b=Team(name="T side", starting_side="T"),
        ),
        players=roster,
        rounds=[rnd],
    )
    return ParsedDemo(data=data, events={"player_death": deaths},
                      ticks=pd.DataFrame(tick_rows))


def _roster(*players: Player) -> list[Player]:
    return list(players)


def test_is_five_e_uses_filename_prefix() -> None:
    players = _roster(Player(steamid=S_ALICE, name="Alice", team="Team 2"))
    deaths = pd.DataFrame({"tick": [1100], "user_steamid": [S_EVE],
                           "attacker_steamid": [S_ALICE]})
    assert is_five_e(_teamplay_demo("g161-20260828_de_dust2.dem", deaths, players))
    assert not is_five_e(_teamplay_demo("9211306538981998348_0.dem", deaths, players))


def test_teamplay_links_and_nan_assister(tmp_path: Path) -> None:
    """Assists / flash-assists / revenge trades build directed links; a NaN
    assister (broadcast omits it) must not invent a fake 'nan' player."""
    players = _roster(
        Player(steamid=S_ALICE, name="Alice", team="Team 2"),
        Player(steamid=S_BOB, name="Bob", team="Team 2"),
        Player(steamid=S_CAROL, name="Carol", team="Team 3"),
        Player(steamid=S_DAVE, name="Dave", team="Team 3"),
    )
    deaths = pd.DataFrame({
        "tick": [1100, 1150, 1300, 1400],
        "user_steamid": [S_ALICE, S_CAROL, S_EVE, S_BOB],
        # 1100 Carol kills Alice -> 1150 Bob avenges (trade, same T side)
        # 1300 Dave kills Eve with Carol assisting via flash
        # 1400 Carol kills Bob, assister NaN (must be ignored)
        "attacker_steamid": [S_CAROL, S_BOB, S_DAVE, S_CAROL],
        "assister_steamid": ["", "", S_CAROL, float("nan")],
        "assistedflash": [False, False, True, False],
    })
    demo = _teamplay_demo("g161-t1.dem", deaths, players)
    cache = DemoCache(tmp_path)
    cache.save(demo.metadata.demo_hash, demo)

    report = build_teamplay_report(
        tmp_path, demo_ratings={}, min_regular_demos=1, stack_threshold=2)
    links = {(l["a_sid"], l["b_sid"]): l for l in report["links"]}
    assert links[(S_CAROL, S_DAVE)]["assists"] == 1
    assert links[(S_CAROL, S_DAVE)]["flash_assists"] == 1
    assert links[(S_BOB, S_ALICE)]["trades"] == 1
    all_sids = {l["a_sid"] for l in report["links"]} | {l["b_sid"] for l in report["links"]}
    assert all(s and s != "nan" for s in all_sids)
    # first kill of the round: Carol won it, Alice lost it
    carol = next(p for p in report["portraits"] if p["name"] == "Carol")
    alice = next(p for p in report["portraits"] if p["name"] == "Alice")
    assert carol["fk_success"] == 1.0 and alice["fk_success"] == 0.0


def test_teamplay_regulars_and_stack_split(tmp_path: Path) -> None:
    """>=min appearances = regular; a match where the regulars play ONE side
    is a stack (round-win attributed); too-few-regulars matches stay mixed.
    (The module skips rounds where present regulars split across sides.)"""
    players = _roster(
        Player(steamid=S_ALICE, name="Alice", team="Team 2"),
        Player(steamid=S_BOB, name="Bob", team="Team 2"),
        Player(steamid=S_CAROL, name="Carol", team="Team 2"),
        Player(steamid=S_DAVE, name="Dave", team="Team 2"),  # whole roster one side
    )
    deaths = pd.DataFrame({
        "tick": [1100],
        "user_steamid": [S_DAVE],
        "attacker_steamid": [S_ALICE],
        "assister_steamid": [S_BOB],
        "assistedflash": [False],
    })
    cache = DemoCache(tmp_path)
    for i in range(1, 4):  # three 5E demos with the same 4 players
        demo = _teamplay_demo(f"g161-m{i}.dem", deaths, players)
        cache.save(demo.metadata.demo_hash, demo)

    report = build_teamplay_report(
        tmp_path, demo_ratings={}, min_regular_demos=3, stack_threshold=3)
    names = {r["name"]: r["appearances"] for r in report["regulars"]}
    assert names == {"Alice": 3, "Bob": 3, "Carol": 3, "Dave": 3}
    assert report["library"]["five_e_demos"] == 3
    # all 3 demos carry >=3 regulars on one side -> stacks, T side won them all
    sv = report["stack_vs_mixed"]
    assert sv["stack_matches"] == 3 and sv["mixed_matches"] == 0
    assert sv["stack"]["round_win_rate"] == 1.0
    assert sv["stack"]["rounds"] == 3
    # assist link Bob->Alice counted per demo; opening duel won 3/3
    link = next(l for l in report["links"] if l["a_sid"] == S_BOB)
    assert link["assists"] == 3
    alice = next(p for p in report["portraits"] if p["name"] == "Alice")
    assert alice["fk_success"] == 1.0
