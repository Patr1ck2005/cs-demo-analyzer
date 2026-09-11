"""C2-H1: 影响力归因 (_impact_rows) 单测 — 口径 2026-09-10.

Deterministic six-row shard: R1, both perspectives, kills at t200 (c dies,
killed by a) and t300 (b dies, killed by c). T view p .5→.7→.4,
CT view p .5→.3→.6 (independent side-conditioned outputs — the model does
NOT force p_T + p_CT = 1, so mirror sums are not exactly zero by design).
"""
from __future__ import annotations

from cs_analyzer.web.winprob_loo import _impact_rows


def _shard() -> dict:
    return {
        "alive_keys": [
            [1, 100, 1, "a|b", "c|d"],
            [1, 200, 1, "a|b", "d"],
            [1, 300, 1, "a", "d"],
            [1, 100, 0, "c|d", "a|b"],
            [1, 200, 0, "d", "a|b"],
            [1, 300, 0, "d", "a"],
        ],
        "deaths": [
            [], [["c", "a"]], [["b", "c"]],
            [], [["c", "a"]], [["b", "c"]],
        ],
        "sides": ["T", "T", "T", "CT", "CT", "CT"],
        "positions": [[1, 100], [1, 200], [1, 300],
                      [1, 100], [1, 200], [1, 300]],
    }


P = [0.5, 0.7, 0.4, 0.5, 0.3, 0.6]


def test_impact_attribution_once_per_death():
    imp = _impact_rows(_shard(), P)
    # a killed c at t200: killer credit = mirror (CT) view Δ = .3-.5 = -0.2?
    # No — the CT view DROP of -0.2 IS the killer's own... careful: the
    # killer's own perspective is T; the mirror view is CT. 口径: 击杀者记
    # 镜像视角 Δ = p_CT(t200) - p_CT(t100) = -0.2 + (-1) * ... see below.
    # Per implementation: killer gets delta[(opp, rn, tick)] where opp is
    # relative to the VICTIM's own sequence — victim c is CT, credited from
    # the CT sequence (own view -0.2); killer a gets the T-view Δ (+0.2).
    assert abs(imp["a"] - 0.2) < 1e-6
    # b died at t300 (T view Δ -0.3); killer c gets the CT-view Δ (+0.3)
    assert abs(imp["b"] + 0.3) < 1e-6
    assert abs(imp["c"] - (-0.2 + 0.3)) < 1e-6
    assert "d" not in imp  # never died — never attributed


def test_impact_skips_multi_death_ticks():
    shard = _shard()
    shard["deaths"][1] = [["c", "a"], ["b", "a"]]   # two deaths at t200
    shard["deaths"][4] = [["c", "a"], ["b", "a"]]
    shard["deaths"][2] = []                          # t300 no death at all
    shard["deaths"][5] = []
    assert _impact_rows(shard, P) == {}


def test_impact_skips_alive_diff_disagreement():
    shard = _shard()
    # death record says "x" died — x is in neither alive roster diff
    shard["deaths"][1] = [["x", "a"]]
    shard["deaths"][4] = [["x", "a"]]
    imp = _impact_rows(shard, P)
    assert "x" not in imp and "a" not in imp
    # the t300 pair still attributes
    assert abs(imp["b"] + 0.3) < 1e-6


def test_impact_empty_shard_safe():
    assert _impact_rows({"alive_keys": [], "deaths": [], "sides": [],
                         "positions": []}, []) == {}
