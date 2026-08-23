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
    assert p["side"][0] == "CT"
    assert all(s == "T" for s in p["side"][i2:])


def test_weapon_names_shortened() -> None:
    d = viewer_data.build_viewer_data(_demo_with_state())
    w = d["players"][0]["w"]
    assert "ak47" in w and "knife" in w
    assert not any(x.startswith("weapon_") for x in w)


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
