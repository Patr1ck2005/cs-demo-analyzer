"""Cross-demo leave-one-out validation for the win-probability model (V1).

The per-demo module trains on the demo itself — its AUC is in-sample and the
page labels it 样本参考. This module answers the honest question the module
docstring always promised: does the model GENERALIZE across matches?

For every cached demo D: train the SAME numpy logistic model on all round
snapshots from every OTHER demo, then evaluate rank-AUC on D's snapshots
(LOO across matches, the web-aggregation note in analysis/win_probability.py).

T3 shard pattern (same as ev_data): per-demo payload = that demo's snapshot
feature rows + labels (compact lists). Only the feature extraction is
cached — the LOO fits themselves are recomputed on every memo build (24
tiny gradient fits ≪ 1s) so threshold changes never need a shard bump.
Cost note: cold path runs the win_probability module for every demo (the
same per-demo memo match pages use); shards make repeat restarts free.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_loo: dict | None = None       # merged report
_shards: list | None = None    # per-demo payloads (shard-backed scan)

#: Minimum snapshots for a held-out demo's AUC to be meaningful — mirrors the
#: module's own in-sample threshold (12 snapshots ≈ a half map's worth).
MIN_HELDOUT = 12


def loo_report() -> dict:
    """Merged LOO validation report (memoized, single-flight).

    Shard memo warmed before the lock — the cold _scan_all path takes the
    same non-reentrant lock _build would hold (see utilitylab_report)."""
    global _loo
    if _loo is None:
        _scan_all()
        with _lock:
            if _loo is None:
                _loo = _build()
    return _loo


def loo_for(demo_hash: str) -> dict | None:
    """This demo's LOO entry ({"auc", "n"}), or None when not computable."""
    d = loo_report().get("demos", {}).get(demo_hash)
    return d if d and d.get("auc") is not None else None


def loo_peek(demo_hash: str) -> dict | None:
    """Read-only variant for request paths: returns the entry only when the
    LOO memo is already warm. A cold first visit must NOT pay the whole-
    library win_probability scan synchronously (the U1 lesson) — wave2
    materializes the memo in the background instead."""
    with _lock:
        memo = _loo
    if memo is None:
        return None
    d = memo.get("demos", {}).get(demo_hash)
    return d if d and d.get("auc") is not None else None


def invalidate_winloo() -> None:
    global _loo, _shards
    with _lock:
        _loo = None
        _shards = None


def _demo_payload(demo) -> dict:
    """Per-demo shard payload: snapshot feature rows + labels (compact)."""
    from cs_analyzer.web import runtime

    result = runtime.analyze_module(demo, "win_probability")
    rows: list[list[float]] = []
    y: list[int] = []
    if result is not None:
        for grp in result.rounds:
            for s in grp:
                rows.append([float(s.alive_diff), float(s.buy_diff),
                             float(s.equip_diff), float(s.planted)])
                y.append(int(s.outcome))
    return {"rows": rows, "y": y}


def _scan_all() -> dict[str, dict]:
    """Whole-library scan with the T3 shard cache (memoized).

    Thread path via the per-demo module memo (shares results with match
    pages); win_probability is a light module (event-level, no per-tick work).
    """
    global _shards
    if _shards is not None:
        return _shards
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir
    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("winloo", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        from cs_analyzer.analysis.library import scan_hashes

        pairs = scan_hashes(cache_dir, missing, _demo_payload)
        for h, payload in pairs:
            snapshots.save_shard("winloo", runtime.out_dir(), cache_dir,
                                 h, payload)
            sharded[h] = payload
    entries = {h: sharded[h] for h in hashes if h in sharded}
    with _lock:
        _shards = entries
        return _shards


def _build() -> dict:
    """LOO fits over the pooled shards; never raises (fail-soft → note)."""
    import numpy as np

    from cs_analyzer.analysis.win_probability import _auc, _fit_logistic, _predict

    per_demo = _scan_all()
    hashes = sorted(per_demo)
    demos_out: dict[str, dict] = {}
    computed: list[tuple[str, float, int]] = []
    try:
        feats = {h: np.array(per_demo[h]["rows"], dtype=float) for h in hashes}
        labels = {h: np.array(per_demo[h]["y"], dtype=float) for h in hashes}
        for h in hashes:
            X_h, y_h = feats[h], labels[h]
            n = int(len(y_h))
            entry: dict = {"n": n, "auc": None}
            two = {h2 for h2 in hashes if h2 != h}
            if n >= MIN_HELDOUT and 0 < y_h.mean() < 1 and two:
                X_train = np.vstack([feats[h2] for h2 in two])
                y_train = np.concatenate([labels[h2] for h2 in two])
                if len(np.unique(y_train)) == 2:
                    theta = _fit_logistic(X_train, y_train)
                    entry["auc"] = round(_auc(_predict(X_h, theta), y_h), 3)
            demos_out[h] = entry
            if entry["auc"] is not None:
                computed.append((h, entry["auc"], n))
    except Exception:  # noqa: BLE001 — validation must never break the page
        return {
            "demos": {}, "mean_auc": None, "n_computed": 0, "n_demos": len(hashes),
            "note": "跨场验证计算失败（特征不可用）",
        }

    mean_auc = None
    n_total = sum(n for _, _, n in computed)
    if computed and n_total:
        mean_auc = round(sum(a * n for _, a, n in computed) / n_total, 3)
    return {
        "demos": demos_out,
        "mean_auc": mean_auc,
        "n_computed": len(computed),
        "n_demos": len(hashes),
        "min_heldout": MIN_HELDOUT,
        "note": (f"跨场留一验证：{len(computed)}/{len(hashes)} 场可评 · "
                 f"加权 AUC {mean_auc:.2f}" if mean_auc is not None
                 else "跨场留一验证：样本尚不可评（每场快照需 ≥"
                      f"{MIN_HELDOUT} 且两类齐全）"),
    }
