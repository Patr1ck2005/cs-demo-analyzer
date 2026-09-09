# -*- coding: utf-8 -*-
"""Unified research evaluation protocol (研究性开发 统一评估协议).

One command answers "did the model get better?" for every iteration round:

  python scripts/research_eval.py                # win-probability model
  python scripts/research_eval.py --model duel   # duel model (Round 2+)

Protocol (frozen, identical for every round — docs/research-ledger.md):
  - data: the T3 shard payloads for the model (winloo shards = per-demo
    snapshot feature rows + labels; the SAME rows the module and the LOO
    memo consume — evaluation can never drift from what the page shows)
  - split: cross-demo leave-one-out (train on every OTHER demo's snapshots,
    score the held-out demo) — the only split that answers "does it
    generalize across matches" on a 35-demo library
  - metrics: weighted AUC (snapshot-weighted mean of per-demo AUCs, the
    memo's headline), pooled AUC (rank-AUC over all held-out predictions),
    Brier score (pooled), log loss (pooled, clipped), and a decile
    calibration table (fixed 10% bins: mean predicted vs observed win rate)
  - output: printed table + output/research/eval_<ts>.json (the ledger
    quotes this file, negative results included)

The script is model-agnostic on purpose: it always fits the module's own
numpy logistic model on whatever feature columns the shards carry, so a
feature-set bump (V1 4 -> V2 12+) flows through without protocol changes.
Cache-only (no .dem parsing); materializes the shard family on first run.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)

OUT_DIR = Path("output/research")
EPS = 1e-6  # log-loss clip


def _eval_winprob(ablate: int | None = None, rating_mode: str = "demo") -> dict:
    """LOO evaluation over the winloo shard family (V1/V2 agnostic).

    `ablate` (optional): drop that 0-based feature column from EVERY demo
    before fitting — the R3 ablation switch (zero shard cost: it reads the
    same payloads and re-fits). FEATURE_NAMES order is the contract.
    `rating_mode="career"` (H-B): rekey the rating_diff column to cross-demo
    career Rating21 (each held-out demo excluded from its own values) before
    fitting — tests whether the same-demo flavor is leakage."""
    import numpy as np

    from cs_analyzer.analysis.win_probability import (
        _auc, _fit_logistic, _predict, brier_score, decile_calibration,
    )
    from cs_analyzer.web import winprob_loo

    per_demo = winprob_loo._scan_all()  # materializes shards on first run
    hashes = sorted(per_demo)
    if not hashes:
        return {"model": "winprob", "error": "no winloo shards — run warmup first"}

    feats = {h: np.array(per_demo[h]["rows"], dtype=float) for h in hashes}
    labels = {h: np.array(per_demo[h]["y"], dtype=float) for h in hashes}
    # first non-empty payload defines the arity (a demo without regular
    # rounds yields an empty row list — not a protocol error)
    n_features = next((int(feats[h].shape[1]) for h in hashes if feats[h].size), 0)
    if ablate is not None:
        if not 0 <= ablate < n_features:
            return {"model": "winprob", "error":
                    f"ablate index {ablate} out of range [0,{n_features})"}
        feats = {h: np.delete(X, ablate, axis=1) for h, X in feats.items()}
        n_features -= 1
    if rating_mode == "career":
        career = winprob_loo._rekey_rating_column(per_demo, hashes)
        rating_col = 9  # FEATURE_NAMES.index("rating_diff") minus ablations above
        if ablate is not None and ablate < 9:
            rating_col -= 1
        for h in hashes:
            vals = career.get(h) or []
            if len(vals) == len(feats[h]):
                feats[h][:, rating_col] = vals

    rows: list[tuple[float, float]] = []  # (p, y) pooled OOS predictions
    per_demo_auc: list[tuple[str, float, int]] = []
    for h in hashes:
        X_h, y_h = feats[h], labels[h]
        others = [h2 for h2 in hashes if h2 != h]
        if len(y_h) < winprob_loo.MIN_HELDOUT or not others:
            continue
        if not (0 < y_h.mean() < 1):
            continue
        X_train = np.vstack([feats[h2] for h2 in others])
        y_train = np.concatenate([labels[h2] for h2 in others])
        if len(np.unique(y_train)) < 2:
            continue
        theta = _fit_logistic(X_train, y_train)
        p = _predict(X_h, theta)
        per_demo_auc.append((h, _auc(p, y_h), int(len(y_h))))
        rows.extend((float(pi), float(yi)) for pi, yi in zip(p, y_h))

    if not rows:
        return {"model": "winprob", "n_features": n_features,
                "ablated": ablate,
                "error": "no demo evaluable under the protocol"}

    P = np.array([r[0] for r in rows])
    Y = np.array([r[1] for r in rows])
    n_total = len(Y)
    # metrics come from the module's own helpers — one source of truth
    # shared with the LOO memo (a protocol drift between script and page
    # would be exactly the stale-number class S3-A1 closed)
    brier = brier_score(P, Y)
    pc = np.clip(P, EPS, 1.0 - EPS)
    logloss = float(-np.mean(Y * np.log(pc) + (1 - Y) * np.log(1 - pc)))
    pooled_auc = _auc(P, Y)

    n_comp = sum(n for _, _, n in per_demo_auc)
    weighted_auc = (sum(a * n for _, a, n in per_demo_auc) / n_comp) if n_comp else None

    calib = decile_calibration(P, Y)

    return {
        "model": "winprob",
        "n_features": n_features,
        "ablated": ablate,
        "rating_mode": rating_mode,
        "n_demos": len(hashes),
        "n_demos_evaluated": len(per_demo_auc),
        "n_snapshots": n_total,
        "weighted_auc": round(weighted_auc, 4) if weighted_auc is not None else None,
        "pooled_auc": round(pooled_auc, 4),
        "brier": round(brier, 4),
        "logloss": round(logloss, 4),
        "calibration": calib,
        "per_demo_auc": [{"demo": h[:12], "auc": round(a, 3), "n": n}
                         for h, a, n in per_demo_auc],
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _eval_duel() -> dict:
    """LOO evaluation over the duelmo shard family (Round 2 对枪模型).

    Identical protocol to the win-probability eval: cross-demo leave-one-out
    with the module's own logistic fit on the shard feature rows."""
    import numpy as np

    from cs_analyzer.analysis.duel_model import duel_feature_names
    from cs_analyzer.analysis.win_probability import (
        _auc, _fit_logistic, _predict, brier_score, decile_calibration,
    )
    from cs_analyzer.web import duel_data

    per_demo = duel_data._scan_all()
    hashes = sorted(per_demo)
    if not hashes:
        return {"model": "duel", "error": "no duelmo shards — run warmup first"}

    n_features = len(duel_feature_names())
    feats = {h: np.array(per_demo[h]["rows"], dtype=float).reshape(-1, n_features)
             for h in hashes}
    labels = {h: np.array(per_demo[h]["y"], dtype=float) for h in hashes}

    rows: list[tuple[float, float]] = []
    per_demo_auc: list[tuple[str, float, int]] = []
    n_duels = 0
    for h in hashes:
        X_h, y_h = feats[h], labels[h]
        others = [h2 for h2 in hashes if h2 != h]
        n_duels += int(len(y_h))
        if len(y_h) < duel_data._MIN_HELDOUT or not others:
            continue
        if not (0 < y_h.mean() < 1):
            continue
        X_train = np.vstack([feats[h2] for h2 in others])
        y_train = np.concatenate([labels[h2] for h2 in others])
        if len(np.unique(y_train)) < 2:
            continue
        theta = _fit_logistic(X_train, y_train)
        p = _predict(X_h, theta)
        per_demo_auc.append((h, _auc(p, y_h), int(len(y_h))))
        rows.extend((float(pi), float(yi)) for pi, yi in zip(p, y_h))

    if not rows:
        return {"model": "duel", "n_features": n_features, "n_duels": n_duels,
                "error": "no demo evaluable under the protocol"}

    P = np.array([r[0] for r in rows])
    Y = np.array([r[1] for r in rows])
    n_total = len(Y)
    brier = brier_score(P, Y)
    pc = np.clip(P, EPS, 1.0 - EPS)
    logloss = float(-np.mean(Y * np.log(pc) + (1 - Y) * np.log(1 - pc)))
    pooled_auc = _auc(P, Y)

    n_comp = sum(n for _, _, n in per_demo_auc)
    weighted_auc = (sum(a * n for _, a, n in per_demo_auc) / n_comp) if n_comp else None

    return {
        "model": "duel",
        "n_features": n_features,
        "n_demos": len(hashes),
        "n_demos_evaluated": len(per_demo_auc),
        "n_snapshots": n_total,
        "n_duels_total": n_duels,
        "weighted_auc": round(weighted_auc, 4) if weighted_auc is not None else None,
        "pooled_auc": round(pooled_auc, 4),
        "brier": round(brier, 4),
        "logloss": round(logloss, 4),
        "calibration": decile_calibration(P, Y),
        "per_demo_auc": [{"demo": h[:12], "auc": round(a, 3), "n": n}
                         for h, a, n in per_demo_auc],
        "excluded_totals": _sum_excluded(per_demo),
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _sum_excluded(per_demo: dict) -> dict:
    totals: dict[str, int] = {}
    for p in per_demo.values():
        for k, v in (p.get("excluded") or {}).items():
            totals[k] = totals.get(k, 0) + int(v)
    return totals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=("winprob", "duel"), default="winprob")
    ap.add_argument("--out", default=None, help="override output JSON path")
    ap.add_argument("--ablate", type=int, default=None,
                    help="winprob only: drop this 0-based feature column "
                         "(FEATURE_NAMES order) before fitting — ablation")
    ap.add_argument("--rating-mode", choices=("demo", "career"), default="demo",
                    help="winprob only: career = rekey rating_diff to "
                         "cross-demo career Rating21 (H-B leakage test)")
    args = ap.parse_args()

    if args.model == "duel":
        result = _eval_duel()
    else:
        result = _eval_winprob(ablate=args.ablate, rating_mode=args.rating_mode)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else OUT_DIR / f"eval_{ts}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # ASCII console labels (GBK console safe); Chinese lives in the JSON/ledger
    print(f"model={result.get('model')} n_features={result.get('n_features')} "
          f"demos={result.get('n_demos_evaluated')}/{result.get('n_demos')} "
          f"snapshots={result.get('n_snapshots')}")
    print(f"weighted_auc={result.get('weighted_auc')} pooled_auc={result.get('pooled_auc')} "
          f"brier={result.get('brier')} logloss={result.get('logloss')}")
    for c in result.get("calibration", []):
        mp, ob = c["mean_pred"], c["obs_rate"]
        print(f"  {c['bin']:>10} n={c['n']:>5} pred={mp if mp is not None else '-'} "
              f"obs={ob if ob is not None else '-'}")
    if result.get("error"):
        print(f"error: {result['error']}")
    print(f"saved: {out_path}")
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
