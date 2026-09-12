"""M2 复盘教练线: suggestions synthesis layer + player_profile eco dim.

E0-E4 口径行 (approved 2026-09-12): the eco dimension judges
eco_hard_rate (kills per own eco round) by its EB interval vs the library
median — duel-dim shape, zero new numeric constants; eco_frag_rate is
context-only. The suggestions layer maps profile verdicts to drill texts
and carries the evidence anchor verbatim.
"""
from __future__ import annotations

import cs_analyzer.web.funlab_data as funlab_data
from cs_analyzer.web.conclusions import player_profile
from cs_analyzer.web.suggestions import DRILL_TEMPLATES, suggestions_from_profile


def _dim(key: str, label: str, verdict: str, anchor: str = "锚定文本") -> dict:
    return {"key": key, "label": label, "verdict": verdict,
            "value": 0.5, "anchor": anchor}


def test_suggestions_maps_strong_and_weak_only() -> None:
    profile = {"dims": [
        _dim("duel", "对枪", "weak"),
        _dim("aim", "枪法纪律", "strong"),
        _dim("loss", "失利模式", "normal"),
        _dim("utility", "道具", "na"),
        _dim("eco", "eco 局表现", "weak"),
    ]}
    out = suggestions_from_profile(profile)
    assert [(s.key, s.status) for s in out] == [
        ("duel", "weak"), ("aim", "strong"), ("eco", "weak")]
    for s in out:
        assert s.drill == DRILL_TEMPLATES[s.key][s.status]
        assert s.evidence == "锚定文本"
        assert s.label


def _eco_row(sid: str, rate: float, lo: float, hi: float, n: int,
             gated: bool = False, frag: float = 0.15) -> dict:
    return {"steamid": sid, "eco_hard_rate": rate, "eco_frag_rate": frag,
            "conf": {"eco_hard_rate": {"lo": lo, "hi": hi, "n": n,
                                       "gated": gated}}}


def test_eco_dim_verdicts_vs_median() -> None:
    # median of [0.4, 0.8, 0.6] = 0.6; the interval decides, not the point
    rep = {"players": [
        _eco_row("S1", 0.4, 0.30, 0.45, 20),
        _eco_row("S2", 0.8, 0.70, 0.90, 30),
        _eco_row("S3", 0.6, 0.55, 0.65, 25),
    ]}
    eco_w = next(d for d in player_profile("S1", funlab_rep=rep)["dims"]
                 if d["key"] == "eco")
    assert eco_w["verdict"] == "weak"
    assert "低于库中位" in eco_w["weak_item"]
    assert "n=20" in eco_w["weak_item"]
    eco_s = next(d for d in player_profile("S2", funlab_rep=rep)["dims"]
                 if d["key"] == "eco")
    assert eco_s["verdict"] == "strong"
    assert "高于库中位" in eco_s["strong_item"]
    eco_n = next(d for d in player_profile("S3", funlab_rep=rep)["dims"]
                 if d["key"] == "eco")
    assert eco_n["verdict"] == "normal"
    assert eco_n.get("weak_item") is None
    # E2: kill-quality context lands in the anchor, never flips the verdict
    assert "含金量" in eco_n["anchor"]


def test_eco_dim_cold_or_gated_is_na(monkeypatch) -> None:
    monkeypatch.setattr(funlab_data, "funlab_peek", lambda: None)
    eco = next(d for d in player_profile("S1")["dims"] if d["key"] == "eco")
    assert eco["verdict"] == "na"
    assert "样本不足" in eco["anchor"]
    gated = {"players": [_eco_row("S1", 0.4, 0.30, 0.45, 2, gated=True)]}
    eco = next(d for d in player_profile("S1", funlab_rep=gated)["dims"]
               if d["key"] == "eco")
    assert eco["verdict"] == "na"


def test_funlab_peek_cold_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(funlab_data, "_scan", None)
    monkeypatch.setattr(funlab_data, "_report", None)
    monkeypatch.setattr(funlab_data, "_report_key", None)
    assert funlab_data.funlab_peek() is None
