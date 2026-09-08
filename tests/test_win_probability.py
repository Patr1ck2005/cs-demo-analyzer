"""Phase V1 — win probability module tests."""
from __future__ import annotations

import numpy as np

from cs_analyzer.analysis.win_probability import (_auc, _fit_logistic, _predict)


def test_logistic_separable_data_auc():
    """Perfectly separable synthetic data → AUC ~1.0 (acceptance gate >0.9)."""
    rng = np.random.default_rng(7)
    n = 400
    X_pos = rng.normal([3, 0.5, 5000, 1, 1], 0.4, size=(n // 2, 5))
    X_neg = rng.normal([-2, -0.3, 2000, 0, 0], 0.4, size=(n // 2, 5))
    X = np.vstack([X_pos, X_neg])
    y = np.array([1] * (n // 2) + [0] * (n // 2), dtype=float)
    theta = _fit_logistic(X, y)
    p = _predict(X, theta)
    auc = _auc(p, y)
    assert auc > 0.9, f"AUC {auc} below the 0.9 acceptance gate"


def test_auc_handles_ties():
    p = np.array([0.5, 0.5, 0.7, 0.3])
    y = np.array([1, 0, 1, 0], dtype=float)
    auc = _auc(p, y)
    # tied pair (one pos one neg at 0.5) + one correct pos + one correct neg:
    # rank math gives (2.5 + 4) / (2*2) = 0.875 — ties average, not coin-flip
    assert abs(auc - 0.875) < 1e-9


def test_probability_monotone_in_alive_diff():
    """More alive advantage → strictly higher win probability (with sane
    feature scales; the model must fit a weak-signal dataset correctly)."""
    rng = np.random.default_rng(11)
    X = rng.normal([0, 0, 0.4, 0, 1], 1.2, size=(800, 5))  # standardized scale
    y = (X[:, 0] + X[:, 1] * 0.5 > 0).astype(float)
    theta = _fit_logistic(X, y)
    probe = np.array([[d, 0, 0.4, 0, 1] for d in range(-4, 5)], dtype=float)
    probs = _predict(probe, theta)
    assert all(probs[i] < probs[i + 1] for i in range(len(probs) - 1)), \
        f"win probability must be monotone in alive advantage: {probs}"


def test_module_runs_on_web_client(web_client):
    from cs_analyzer.web import runtime
    from tests.conftest import build_parsed_demo

    demo = build_parsed_demo()
    result = runtime.analyze_module(demo, "win_probability")
    assert result is not None
    # synthetic demo may be too small to fit — must degrade gracefully
    assert result.sample_note
