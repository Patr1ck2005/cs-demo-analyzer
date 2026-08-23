"""Tests for the canvas viewer-data artifact (Phase C M2)."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from cs_analyzer.web import viewer_data

from .conftest import S_ALICE, build_parsed_demo


def _demo_with_state():
    """2 rounds; Alice walks +x, swaps side at round 2 (halftime proxy),
    carries yaw/hp/armor/active_weapon_name state."""
    n1, n2 = 40, 40
    ticks = pd.DataFrame(
        {
            "tick": list(range(0, 2560, 64)) + list(range(2560, 5120, 64)),
            "steamid": [S_ALICE] * (n1 + n2),
            "X": [float(i * 8) for i in range(n1)] + [500.0 - i * 4 for i in range(n2)],
            "Y": [10.0] * (n1 + n2),
            "yaw": [90.0] * n1 + [-135.0] * n2,
            "health": [100] * n1 + [55] * n2,
            "armor": [100] * (n1 + n2),
            "is_alive": [True] * n1 + [False] * n2,
            "team_num": [3.0] * n1 + [2.0] * n2,
            "active_weapon_name": ["weapon_ak47"] * n1 + ["weapon_knife"] * n2,
        }
    )
    return build_parsed_demo(ticks=ticks)


def test_build_viewer_data_schema() -> None:
    d = viewer_data.build_viewer_data(_demo_with_state())
    assert d["viewer_version"] == viewer_data.VIEWER_DATA_VERSION
    assert d["tick_rate"] == 64 and d["stride"] == 8
    assert len(d["segments"]) == 2
    assert d["segments"][0]["winner_side"] in ("T", "CT")
    assert d["ammo"] is False
    assert d["map"]["image_url"] == "/maps/de_mirage.png"
    assert {"min_x", "max_x", "min_y", "max_y"} <= set(d["map"]["bounds"])


def test_snapshot_stride_and_side_follows_team_num() -> None:
    d = viewer_data.build_viewer_data(_demo_with_state())
    p = d["players"][0]
    assert p["t"][1] - p["t"][0] == 8  # 8-tick stride
    i2 = next(i for i, t in enumerate(p["t"]) if t >= 2560)
    # v2 side enum: 0=T, 1=CT, 2=unknown
    assert p["side"][0] == viewer_data.SIDE_CT
    assert all(s == viewer_data.SIDE_T for s in p["side"][i2:])
    # roster hoists the first observed side for the client
    assert d["roster"][0]["side_first"] == "CT"


def test_weapon_interning() -> None:
    """v2 interns weapon names: snapshots carry indexes into weapon_table."""
    d = viewer_data.build_viewer_data(_demo_with_state())
    table = d["weapon_table"]
    assert "ak47" in table and "knife" in table
    assert not any(x.startswith("weapon_") for x in table)
    w = d["players"][0]["w"]
    assert all(isinstance(i, int) and 0 <= i < len(table) for i in w)
    assert table[w[0]] == "ak47"


def test_dead_rows_zeroed_alive_flag() -> None:
    d = viewer_data.build_viewer_data(_demo_with_state())
    p = d["players"][0]
    # round 2 starts at tick 2560; find the first snapshot at/after it
    i2 = next(i for i, t in enumerate(p["t"]) if t >= 2560)
    assert all(p["alive"][:i2])
    assert not any(p["alive"][i2:])
    assert all(h == 55 for h in p["hp"][i2:])  # hp follows the dead half


def test_roster_skips_positionless_players() -> None:
    ticks = pd.DataFrame(
        {
            "tick": [0, 64],
            "steamid": [S_ALICE] * 2,
            "X": [1.0, 2.0],
            "Y": [0.0, 0.0],
            "is_alive": [True] * 2,
            "team_num": [3.0] * 2,
        }
    )
    demo = build_parsed_demo(ticks=ticks)  # Bob/Carol/Dave have no tick rows
    d = viewer_data.build_viewer_data(demo)
    assert [r["steamid"] for r in d["roster"]] == [S_ALICE]


def test_stale_version_treated_missing(tmp_path) -> None:
    h = "abc123"
    vdir = tmp_path / h / "viewer"
    vdir.mkdir(parents=True)
    payload = {"viewer_version": viewer_data.VIEWER_DATA_VERSION - 1}
    (vdir / "viewer_data.json").write_text(json.dumps(payload), encoding="utf-8")
    assert not viewer_data.is_ready(h, tmp_path)


def test_nan_positions_forward_filled() -> None:
    ticks = pd.DataFrame(
        {
            "tick": [0, 8, 16, 24, 32],
            "steamid": [S_ALICE] * 5,
            "X": [10.0, float("nan"), float("nan"), 30.0, 40.0],
            "Y": [5.0] * 5,
            "is_alive": [True] * 5,
            "team_num": [3.0] * 5,
        }
    )
    d = viewer_data.build_viewer_data(build_parsed_demo(ticks=ticks))
    xs = d["players"][0]["x"]
    assert xs[1] == 10.0 and xs[2] == 10.0  # NaNs keep the last finite position
    assert xs[3] == 30.0  # resumes tracking when data returns


# ---------- v2: events with coordinates / durations / bombs / economy ----------


def _walking_ticks():
    """Alice walking +x through both rounds (positions for throw reconstruction)."""
    n = 80
    return pd.DataFrame(
        {
            "tick": list(range(0, 5120, 64)),
            "steamid": [S_ALICE] * n,
            "X": [float(i * 8) for i in range(n)],
            "Y": [10.0] * n,
            "is_alive": [True] * n,
            "team_num": [3.0] * n,
        }
    )


def test_kills_carry_coordinates_and_headshot() -> None:
    demo = build_parsed_demo(
        ticks=_walking_ticks(),
        events={
            "player_death": pd.DataFrame(
                {
                    "tick": [1000, 2000],
                    "attacker_name": ["Alice", float("nan")],
                    "user_name": ["Bob", "Carol"],
                    "attacker_steamid": [S_ALICE, ""],
                    "user_steamid": ["sid_bob", "sid_carol"],
                    "attacker_X": [100.5, float("nan")],  # suicide/world death -> null
                    "attacker_Y": [20.25, float("nan")],
                    "user_X": [300.0, 310.0],
                    "user_Y": [40.0, 41.0],
                    "headshot": [1, 0],
                    "weapon": ["weapon_ak47", "world"],
                }
            )
        },
    )
    kills = viewer_data.build_viewer_data(demo)["events"]["kills"]
    assert len(kills) == 2
    k0 = kills[0]
    assert k0["ax"] == 100.5 and k0["ay"] == 20.25
    assert k0["vx"] == 300.0 and k0["vy"] == 40.0
    assert k0["hs"] == 1
    assert k0["att"] == S_ALICE and k0["vic"] == "sid_bob"
    assert k0["an"] == "Alice" and k0["vn"] == "Bob"
    # weapon interned; table resolves it back to the short name
    table = viewer_data.build_viewer_data(demo)["weapon_table"]
    assert table[k0["wi"]] == "ak47"
    k1 = kills[1]
    assert k1["ax"] is None and k1["ay"] is None  # null, not 0.0
    json.dumps(kills, allow_nan=False)  # strict JSON


def test_utilities_real_duration_and_throw_reconstruction() -> None:
    """smokegrenade_expired entity match yields the real lifetime; the throw
    origin is interpolated from Alice's own walk before the landing tick."""
    demo = build_parsed_demo(
        ticks=_walking_ticks(),
        events={
            "smokegrenade_detonate": pd.DataFrame(
                {"tick": [2560], "entityid": [7], "x": [400.0], "y": [50.0],
                 "user_steamid": [S_ALICE]}
            ),
            "smokegrenade_expired": pd.DataFrame(
                {"tick": [2560 + 15 * 64], "entityid": [7]}  # lived 15s
            ),
        },
    )
    utils = viewer_data.build_viewer_data(demo)["events"]["utilities"]
    assert len(utils) == 1
    u = utils[0]
    assert u["kind"] == "smoke" and u["tick"] == 2560
    assert u["dur_s"] == 15.0
    assert u["tt"] == 2560 - int(2.0 * 64)  # smoke flight estimate 2.0s
    # Alice's rows sit every 64 ticks: exact sample at the throw tick (no interp)
    assert u["tx"] == 8.0 * (((2560 - 128)) / 64)
    assert u["sid"] == S_ALICE


def test_blind_events_extracted() -> None:
    demo = build_parsed_demo(
        ticks=_walking_ticks(),
        events={
            "player_blind": pd.DataFrame(
                {"tick": [1500], "blind_duration": [3.25],
                 "attacker_steamid": [S_ALICE], "user_steamid": ["sid_victim"]}
            )
        },
    )
    blinds = viewer_data.build_viewer_data(demo)["events"]["blinds"]
    assert blinds == [{"tick": 1500, "dur": 3.2, "att": S_ALICE, "vic": "sid_victim"}]


def test_bomb_events_with_coordinate_fallback() -> None:
    """No user_X on the event -> planter position interpolated from tick rows."""
    demo = build_parsed_demo(
        ticks=_walking_ticks(),
        events={
            "bomb_planted": pd.DataFrame(
                {"tick": [1300], "site": ["B"], "user_steamid": [S_ALICE]}
            ),
            "bomb_defused": pd.DataFrame(
                {"tick": [1900], "site": [float("nan")], "user_steamid": [S_ALICE]}
            ),
        },
    )
    bombs = viewer_data.build_viewer_data(demo)["events"]["bombs"]
    assert len(bombs) == 2
    b0 = bombs[0]
    assert b0["type"] == "plant" and b0["site"] == "B" and b0["sid"] == S_ALICE
    # Alice is at X=8*(tick/64) -> at tick 1300: ~162.5
    assert b0["x"] == round(8 * (1300 / 64), 1)
    d0 = bombs[1]
    assert d0["type"] == "defuse" and d0["site"] is None


def test_teams_from_begin_new_match() -> None:
    demo = build_parsed_demo(
        ticks=_walking_ticks(),
        events={"begin_new_match": pd.DataFrame(
            {"t_team_name": ["Fury"], "ct_team_name": ["Nova"]}
        )},
    )
    assert viewer_data.build_viewer_data(demo)["teams"] == {"t": "Fury", "ct": "Nova"}
    demo2 = build_parsed_demo(ticks=_walking_ticks())
    assert viewer_data.build_viewer_data(demo2)["teams"] == {"t": "", "ct": ""}


def test_layers_shots_and_economy() -> None:
    demo = build_parsed_demo(
        ticks=_walking_ticks(),
        events={
            "weapon_fire": pd.DataFrame(
                {"tick": [1000, 1008, 2000], "weapon": ["weapon_ak47", "weapon_ak47", "world"],
                 "user_steamid": [S_ALICE, S_ALICE, "sid_t0"],
                 "user_X": [128.0, 129.0, float("nan")], "user_Y": [10.0, 10.0, float("nan")]}
            ),
            "item_purchase": pd.DataFrame(
                {"tick": [100], "item_name": ["weapon_ak47"], "cost": [2700],
                 "steamid": [S_ALICE]}
            ),
        },
    )
    layers = viewer_data.build_viewer_layers(demo)
    assert layers["layer_version"] == viewer_data.LAYER_VERSION
    shots = layers["shots"]
    assert len(shots) == 2  # Team-0 shooter without coords skipped
    assert shots[0] == {"tick": 1000, "x": 128.0, "y": 10.0, "sid": S_ALICE,
                        "wi": shots[0]["wi"]}
    assert layers["weapon_table"][shots[0]["wi"]] == "ak47"
    eco = layers["economy"]["rounds"]["1"][S_ALICE]
    assert eco["spend"] == 2700 and eco["nades"] == 0
    assert layers["weapon_table"][eco["weapons"][0]] == "ak47"


def test_payload_gzip_budget() -> None:
    import gzip

    payload = viewer_data.build_viewer_data(_demo_with_state())
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(gzip.compress(raw)) < 1_000_000  # budget: <=1.0 MB gzip
