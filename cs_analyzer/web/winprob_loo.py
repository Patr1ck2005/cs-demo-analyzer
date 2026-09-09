"""Cross-demo leave-one-out validation for the win-probability model (V2).

The per-demo module trains on the demo itself — its AUC is in-sample and the
page labels it 样本参考. This module answers the honest question the module
docstring always promised: does the model GENERALIZE across matches?

For every cached demo D: train the SAME numpy logistic model on all round
snapshots from every OTHER demo, then evaluate rank-AUC on D's snapshots
(LOO across matches). V2 upgrade (docs/research-ledger.md Round 1): the
per-demo OOS predictions are KEPT in the memo — the match page serves that
curve as the honest "cross-match" line (replacing the in-sample bootstrap
band as the headline curve), plus pooled Brier + decile calibration from
analysis/stats helpers.

T3 shard pattern (same as ev_data): per-demo payload = that demo's snapshot
feature rows (FEATURE_NAMES order) + labels (compact lists) + meta (model
version, feature count). Only the feature extraction is cached — the LOO
fits themselves are recomputed on every memo build (35 tiny gradient fits
≪ 1s) so threshold changes never need a shard bump. Legacy 4-wide payloads
(V1 shards) are skipped as missing — the src8 fingerprint rolls the whole
family on a producer change anyway; this guard is for hand-copied dirs.
Cost note: cold path runs the win_probability module for every demo (the
same per-demo memo match pages use); shards make repeat restarts free.
"""
from __future__ import annotations

import threading

from cs_analyzer.analysis.win_probability import FEATURE_NAMES, N_FEATURES

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


def loo_memo_peek() -> dict | None:
    """Whole LOO memo when warm (read-only, never computes — U1 lesson).

    The match page reads the pooled OOS metrics (brier/calibration) and the
    per-demo OOS curve from here; None means "show the in-sample fallback"."""
    with _lock:
        return _loo


def invalidate_winloo() -> None:
    global _loo, _shards
    with _lock:
        _loo = None
        _shards = None


def _demo_payload(demo) -> dict:
    """Per-demo shard payload: snapshot feature rows + labels (compact).

    Rows follow the module's FEATURE_NAMES order over BOTH perspectives
    (side in V2 is a feature — the T-view page curve is a slice of this).
    `positions` ([round, tick] per row) lets the LOO build serve a
    positionally-aligned OOS curve to the page; `alive_keys` (same order)
    carries each snapshot's alive-roster keys so the merge layer can rekey
    the rating_diff column to cross-demo career ratings (H-B) without
    touching the module."""
    from cs_analyzer.analysis.win_probability import _feature_row
    from cs_analyzer.web import runtime

    result = runtime.analyze_module(demo, "win_probability")
    rows: list[list[float]] = []
    y: list[int] = []
    sides: list[str] = []
    positions: list[list[int]] = []
    alive_keys: list[list] = []
    if result is not None:
        for s in result.snapshots_all:
            rows.append(_feature_row(s))
            y.append(int(s.outcome))
            sides.append(s.side)
            positions.append([int(s.round), int(s.tick)])
        alive_keys = result.alive_keys
    return {
        "rows": rows, "y": y, "sides": sides, "positions": positions,
        "alive_keys": alive_keys,
        "meta": {"model": result.model_version if result is not None else "?",
                 "n_features": N_FEATURES},
    }


def _career_ratings(exclude_hash: str) -> dict[str, float]:
    """Round-weighted cross-demo Rating21 per player, EXCLUDING one demo.

    Reads the rating21 shard family (memoized there; wave2 materializes it
    before the winloo step). H-B: rows rekeyed to these values never contain
    same-demo outcome information."""
    from cs_analyzer.web import rating21_data

    num_den: dict[str, list[float]] = {}
    for h2, sh in rating21_data.shards():
        if h2 == exclude_hash:
            continue
        n = int(sh.get("rounds") or 0)
        if n <= 0:
            continue
        for sid, p in sh.get("players", {}).items():
            cell = num_den.setdefault(sid, [0.0, 0])
            cell[0] += float(p.get("r21") or 0.0) * n
            cell[1] += n
    return {sid: cell[0] / cell[1] for sid, cell in num_den.items() if cell[1]}


def _rekey_rating_column(per_demo: dict, hashes: list[str]) -> dict[str, list[float]]:
    """Rating-column (rating_diff) values per demo rekeyed to cross-demo
    career ratings. Returns {hash: [values aligned with rows]}. A player
    unknown outside the held-out demo falls back to the pool career mean
    (computed over every OTHER demo once, then reused)."""
    import numpy as np

    # pool mean over ALL demos' career values (fallback for one-demo players)
    all_career: dict[str, list[float]] = {}
    for h in hashes:
        for sid, v in _career_ratings(h).items():
            all_career.setdefault(sid, []).append(v)
    pool_mean = (float(np.mean([v for vals in all_career.values() for v in vals]))
                 if all_career else 1.0)

    replaced: dict[str, list[float]] = {}
    for h in hashes:
        career = _career_ratings(h)  # excludes THIS demo (no leakage)
        vals: list[float] = []
        for key in per_demo[h].get("alive_keys") or []:
            _rn, _tk, _s01, mine, opp = key[0], key[1], key[2], key[3], key[4]
            m_sids = mine.split("|") if mine else []
            o_sids = opp.split("|") if opp else []
            diff = (sum(career.get(s, pool_mean) for s in m_sids)
                    - sum(career.get(s, pool_mean) for s in o_sids))
            vals.append(float(diff))
        replaced[h] = vals
    return replaced


def _scan_all() -> dict[str, dict]:
    """Whole-library scan with the T3 shard cache (memoized).

    Thread path via the per-demo module memo (shares results with match
    pages); win_probability is a light module (event-level, no per-tick
    work beyond the V2 tick-state lookups).
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
    # shape guard: only current-shape payloads (V2 n_features + sides +
    # alive_keys — career rekey silently degrades without the keys)
    entries = {h: p for h, p in sharded.items()
               if h in set(hashes) and isinstance(p, dict)
               and p.get("meta", {}).get("n_features") == N_FEATURES
               and isinstance(p.get("alive_keys"), list)}
    with _lock:
        _shards = entries
        return _shards


def _build(rating_mode: str = "demo") -> dict:
    """LOO fits over the pooled shards; never raises (fail-soft → note).

    rating_mode: "demo" (default — the rating_diff column carries this
    demo's own Rating21 values, current page behavior) or "career"
    (H-B — the column is rekeyed to cross-demo career Rating21 computed
    EXCLUDING each held-out demo; answers whether the same-demo flavor of
    rating_diff is a leakage-flavored gain)."""
    import numpy as np

    from cs_analyzer.analysis.win_probability import (
        _auc, _fit_logistic, _predict, brier_score, decile_calibration,
    )

    per_demo = _scan_all()
    hashes = sorted(per_demo)
    demos_out: dict[str, dict] = {}
    computed: list[tuple[str, float, int]] = []
    pooled_p: list[float] = []
    pooled_y: list[float] = []
    oos_curves: dict[str, dict] = {}
    try:
        feats = {h: np.array(per_demo[h]["rows"], dtype=float) for h in hashes}
        labels = {h: np.array(per_demo[h]["y"], dtype=float) for h in hashes}
        career_vals: dict[str, list[float]] = {}
        if rating_mode == "career":
            career_vals = _rekey_rating_column(per_demo, hashes)
            rating_col = FEATURE_NAMES.index("rating_diff")
            for h in hashes:
                if len(career_vals.get(h, [])) == len(feats[h]):
                    feats[h][:, rating_col] = career_vals[h]
        for h in hashes:
            X_h, y_h = feats[h], labels[h]
            n = int(len(y_h))
            entry: dict = {"n": n, "auc": None}
            two = [h2 for h2 in hashes if h2 != h]
            if n >= MIN_HELDOUT and 0 < y_h.mean() < 1 and two:
                X_train = np.vstack([feats[h2] for h2 in two])
                y_train = np.concatenate([labels[h2] for h2 in two])
                if len(np.unique(y_train)) == 2:
                    theta = _fit_logistic(X_train, y_train)
                    p_h = _predict(X_h, theta)
                    entry["auc"] = round(_auc(p_h, y_h), 3)
                    # V2: keep the OOS predictions — the honest curve the
                    # match page serves when this memo is warm (no bootstrap
                    # band: band cost across 35 pooled refits was judged
                    # not worth it this round, ledger notes it). Rows keep
                    # shard order; `oos_by_pos` maps [round, tick] → p for
                    # position-aligned page rendering (T-view slice only).
                    demos_out[h] = entry
                    computed.append((h, entry["auc"], n))
                    pooled_p.extend(float(v) for v in p_h)
                    pooled_y.extend(float(v) for v in y_h)
                    by_pos: dict[str, float] = {}
                    pos_rows = per_demo[h].get("positions") or []
                    side_rows = per_demo[h].get("sides") or []
                    for i, pv in enumerate(p_h):
                        if i < len(pos_rows) and i < len(side_rows):
                            # side in the key: T and CT share (round, tick)
                            s01 = 1 if side_rows[i] == "T" else 0
                            by_pos[f"{pos_rows[i][0]}:{pos_rows[i][1]}:{s01}"] = round(float(pv), 3)
                    oos_curves[h] = {"p": [round(float(v), 3) for v in p_h],
                                     "y": [int(v) for v in y_h],
                                     "by_pos": by_pos}
            if h not in demos_out:
                demos_out[h] = entry
    except Exception:  # noqa: BLE001 — validation must never break the page
        return {
            "demos": {}, "mean_auc": None, "n_computed": 0, "n_demos": len(hashes),
            "note": "跨场验证计算失败（特征不可用）",
        }

    mean_auc = None
    n_total = sum(n for _, _, n in computed)
    if computed and n_total:
        mean_auc = round(sum(a * n for _, a, n in computed) / n_total, 3)

    pooled = {"brier": None, "logloss": None, "calibration": None}
    pooled_auc = None
    if pooled_p:
        P = np.array(pooled_p)
        Y = np.array(pooled_y)
        pooled_auc = round(_auc(P, Y), 3)
        pc = np.clip(P, 1e-6, 1 - 1e-6)
        pooled = {
            "brier": round(brier_score(P, Y), 4),
            "logloss": round(float(-np.mean(Y * np.log(pc) + (1 - Y) * np.log(1 - pc))), 4),
            "calibration": decile_calibration(P, Y),
        }

    note = (f"跨场留一验证：{len(computed)}/{len(hashes)} 场可评 · "
            f"加权 AUC {mean_auc:.2f}" if mean_auc is not None
            else "跨场留一验证：样本尚不可评（每场快照需 ≥"
                 f"{MIN_HELDOUT} 且两类齐全）")
    if pooled["brier"] is not None:
        note += f" · Brier {pooled['brier']:.3f}（混池）"
    return {
        "demos": demos_out,
        "oos_curves": oos_curves,
        "mean_auc": mean_auc,
        "pooled_auc": pooled_auc,
        "brier": pooled["brier"],
        "logloss": pooled["logloss"],
        "calibration": pooled["calibration"],
        "n_computed": len(computed),
        "n_demos": len(hashes),
        "n_features": N_FEATURES,
        "model_version": "V2",
        "rating_mode": rating_mode,
        "min_heldout": MIN_HELDOUT,
        "note": note,
    }
