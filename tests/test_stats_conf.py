"""Phase R1: statistical rigor toolkit (analysis/stats.py)."""
from __future__ import annotations

import math

import pytest

from cs_analyzer.analysis import stats
from cs_analyzer.analysis.stats import attach_conf, shrunk_mean, wilson_interval


class TestWilson:
    def test_contains_point_estimate(self):
        for s in (0, 1, 3, 7, 10):
            for n in (10, 50, 200):
                lo, hi = wilson_interval(s, n)
                p = s / n
                assert lo - 1e-9 <= p <= hi + 1e-9

    def test_monotone_narrowing(self):
        # more samples -> narrower interval (same p)
        lo5, hi5 = wilson_interval(3, 5)
        lo50, hi50 = wilson_interval(30, 50)
        assert (hi50 - lo50) < (hi5 - lo5)

    def test_one_of_one_is_not_one(self):
        # the “1局0胜” lesson: 100% from n=1 must not read as certainty
        lo, hi = wilson_interval(1, 1)
        assert lo < 0.5
        assert hi <= 1.0

    def test_zero_and_full_bounds(self):
        lo, hi = wilson_interval(0, 20)
        assert lo == 0.0 and hi < 0.2
        lo, hi = wilson_interval(20, 20)
        assert hi == 1.0 and lo > 0.8

    def test_n_zero_stable(self):
        assert wilson_interval(0, 0) == (0.0, 0.0)

    def test_symmetric_extremes(self):
        lo0, hi0 = wilson_interval(0, 10)
        lo1, hi1 = wilson_interval(10, 10)
        assert math.isclose(1 - hi0, lo1, abs_tol=1e-9)


class TestShrink:
    def test_converges_to_raw(self):
        assert shrunk_mean(2.0, 10_000, prior=1.0, k=4) == pytest.approx(2.0, abs=1e-3)

    def test_n_zero_is_prior(self):
        assert shrunk_mean(9.9, 0, prior=1.5) == 1.5

    def test_n_one_pulls_toward_prior(self):
        s = shrunk_mean(10.0, 1, prior=1.0, k=4)
        assert 1.0 < s < 10.0
        assert s == pytest.approx((1 * 10.0 + 4 * 1.0) / 5)

    def test_never_overshoots(self):
        # shrinkage stays between raw value and prior
        s = shrunk_mean(0.0, 2, prior=5.0, k=4)
        assert 0.0 <= s <= 5.0


class TestAttachConf:
    def test_rate_rows_get_wilson(self):
        rows = [
            {"player": "A", "rate": 0.6, "rounds": 100},
            {"player": "B", "rate": 0.6, "rounds": 2},
        ]
        attach_conf(rows, "rate", "rounds", kind="rate", gate_n=3)
        a, b = rows
        assert a["conf"]["gated"] is False
        assert b["conf"]["gated"] is True
        # same p, wider interval at small n
        assert (b["conf"]["hi"] - b["conf"]["lo"]) > (a["conf"]["hi"] - a["conf"]["lo"])
        assert a["conf"]["n"] == 100 and b["conf"]["n"] == 2

    def test_rate_from_fractional_rate(self):
        # rate stored as e.g. 0.1234 with n=97: implied count is fractional;
        # Wilson still works and n stays the integer trial count.
        rows = [{"rate": 0.3333, "n": 97}]
        attach_conf(rows, "rate", "n", kind="rate")
        lo, hi = rows[0]["conf"]["lo"], rows[0]["conf"]["hi"]
        assert lo < 0.3333 < hi

    def test_rate_percentage_normalized(self):
        rows = [{"rate": 61.0, "n": 90}]
        attach_conf(rows, "rate", "n", kind="rate")
        assert rows[0]["conf"]["lo"] < 0.61 < rows[0]["conf"]["hi"]

    def test_mean_rows_get_shrunk(self):
        rows = [
            {"v": 100.0, "demos": 40},
            {"v": 100.0, "demos": 1},
            {"v": 100.0, "demos": 8},
        ]
        attach_conf(rows, "v", "demos", kind="mean", k=4)
        # pool mean is 100 (same raw everywhere) -> no shrink movement
        for r in rows:
            assert r["shrunk"] == pytest.approx(100.0, abs=1e-6)
            assert r["conf"]["gated"] == (r["demos"] < stats.DEFAULT_GATE_N)

    def test_mean_shrink_pulls_small_n_to_pool(self):
        rows = [
            {"v": 500.0, "demos": 50},   # pool mean ≈ 500*(50+8)/(58)= 500
            {"v": 5000.0, "demos": 2},   # outlier with tiny n
            {"v": 500.0, "demos": 6},
        ]
        attach_conf(rows, "v", "demos", kind="mean", k=4)
        pool = (500.0 * 50 + 5000.0 * 2 + 500.0 * 6) / 58.0
        small = rows[1]
        raw = 5000.0
        expected = (2 * raw + 4 * pool) / 6
        assert small["shrunk"] == pytest.approx(expected, abs=1e-3)
        # shrunk value sits between pool and raw
        assert pool < small["shrunk"] < raw
        # conf brackets raw<->shrunk
        assert small["conf"]["lo"] == pytest.approx(min(raw, expected), abs=1e-3)
        assert small["conf"]["hi"] == pytest.approx(max(raw, expected), abs=1e-3)

    def test_mean_n_zero_gated(self):
        rows = [{"v": 12.0, "demos": 0}]
        attach_conf(rows, "v", "demos", kind="mean")
        assert rows[0]["shrunk"] == 0.0  # prior defaults to 0 (empty pool)
        assert rows[0]["conf"]["gated"] is True

    def test_empty_board(self):
        assert attach_conf([], "v", "n") == []

    def test_missing_n_key_gates(self):
        rows = [{"rate": 0.5}]
        attach_conf(rows, "rate", "n", kind="rate")
        assert rows[0]["conf"]["gated"] is True
        assert rows[0]["conf"]["n"] == 0
