"""Phase V2 — economy EV module tests."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis.runner import AnalysisRunner
from tests.conftest import build_parsed_demo, S_ALICE, S_BOB


def _demo_with_purchases():
    ticks = pd.DataFrame({
        "tick": [100, 200, 300, 400] * 2,
        "steamid": [S_ALICE] * 4 + [S_BOB] * 4,
        "X": [0.0] * 8, "Y": [0.0] * 8,
        "is_alive": [True] * 8,
        "team_num": [3.0] * 4 + [2.0] * 4,
    })
    events = {
        "item_purchase": pd.DataFrame({
            "tick": [150, 150, 150, 150],
            "user_steamid": [S_ALICE, S_ALICE, S_BOB, S_BOB],
            "item_name": ["item_ak47", "item_glock", "item_awp", "item_deagle"],
            "cost": [2700, 200, 4750, 700],
        }),
        "player_death": pd.DataFrame({
            "tick": [900],
            "attacker_name": ["Alice"], "user_name": ["Bob"],
            "attacker_steamid": [S_ALICE], "user_steamid": [S_BOB],
            "assister_steamid": [""],
        }),
    }
    return build_parsed_demo(ticks=ticks, events=events)


def test_module_runs_and_cells_gated():
    demo = _demo_with_purchases()
    res = AnalysisRunner().run_one(demo, "economy_ev")
    assert res.cells is not None
    # small synthetic → most cells under MIN_SAMPLES → win_rate None (grey)
    assert res.min_samples == 5
    for c in res.cells:
        if c.n < res.min_samples:
            assert c.win_rate is None, "sub-gate cells must not expose a rate"
        else:
            assert c.win_rate is not None


def test_min_samples_gate():
    from cs_analyzer.analysis.economy_ev import MIN_SAMPLES

    assert MIN_SAMPLES == 5, "user-approved statistical gate"
