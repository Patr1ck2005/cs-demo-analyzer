"""Cross-demo duel-model shards + per-player 对枪实力 aggregation (Round 2).

T3 shard family ``duelmo``: per-demo payload = that demo's duel feature rows
(duel_model._feature_row order) + labels + involvement meta. The LOO fits
follow the winprob_loo precedent — recomputed per memo build (35 tiny fits ≪
1s), shards make restarts free.

Per-player board (批准口径 B): every judged duel counts once for EACH member
(attacker perspective p; victim perspective 1−p). The model expectation is
the leave-one-out p — the honest "context-adjusted" number; 超预期差 =
actual − expected on the expectation subset, EB shrinkage (k=32) is
display-only. Players under DUEL_GATE_N duels stay visible but greyed
(gated=灰显不隐藏, R1 precedent).

IMPORTANT (X4b/U1 lesson): report-level access warms shards BEFORE locking;
request paths only *peek* at the warm memo (wave2 materializes it).
"""
from __future__ import annotations

import threading

from cs_analyzer.analysis.duel_model import duel_feature_names

_lock = threading.Lock()
_report: dict | None = None
_shards: dict | None = None

#: display gate for the career board (rows stay visible, greyed)
DUEL_GATE_N = 20
#: EB pseudo-count for the 超预期差 display shrinkage (per-event k, R1 stats)
_K_EVENT = 32

_MIN_HELDOUT = 12


def invalidate_duelmo() -> None:
    global _report, _shards
    with _lock:
        _report = None
        _shards = None


def _demo_payload(demo) -> dict:
    from cs_analyzer.analysis.duel_model import _feature_row
    from cs_analyzer.web import runtime

    result = runtime.analyze_module(demo, "duel_model")
    rows: list[list[float]] = []
    y: list[int] = []
    duels: list[dict] = []
    for s in result.samples:
        rows.append(_feature_row(s))
        y.append(int(s.y))
        duels.append({"att": s.attacker, "vic": s.victim, "y": int(s.y),
                      "round": int(s.round), "tick": int(s.tick)})
    roster = {p.steamid: p.name for p in demo.players}
    return {"rows": rows, "y": y, "duels": duels, "roster": roster,
            "excluded": result.n_excluded,
            "meta": {"n_features": len(duel_feature_names())}}


def _scan_all() -> dict[str, dict]:
    """Whole-library scan with the T3 shard cache (memoized, family duelmo)."""
    global _shards
    if _shards is not None:
        return _shards
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir
    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("duelmo", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        from cs_analyzer.analysis.library import scan_hashes

        pairs = scan_hashes(cache_dir, missing, _demo_payload)
        for h, payload in pairs:
            snapshots.save_shard("duelmo", runtime.out_dir(), cache_dir,
                                 h, payload)
            sharded[h] = payload
    n_feat = len(duel_feature_names())
    entries = {h: p for h, p in sharded.items()
               if h in set(hashes) and isinstance(p, dict)
               and p.get("meta", {}).get("n_features") == n_feat}
    with _lock:
        _shards = entries
        return _shards


def _build() -> dict:
    """LOO duel model + per-player 对枪实力 board (fail-soft → note)."""
    import numpy as np

    from cs_analyzer.analysis.duel_model import _feature_row  # noqa: F401 (row contract doc)
    from cs_analyzer.analysis.stats import wilson_interval
    from cs_analyzer.analysis.win_probability import (
        _auc, _fit_logistic, _predict, brier_score, decile_calibration,
    )

    per_demo = _scan_all()
    hashes = sorted(per_demo)
    n_feat = len(duel_feature_names())
    feats: dict[str, np.ndarray] = {}
    labels: dict[str, np.ndarray] = {}
    for h in hashes:
        feats[h] = np.array(per_demo[h]["rows"], dtype=float).reshape(-1, n_feat)
        labels[h] = np.array(per_demo[h]["y"], dtype=float)

    # ---- LOO: per-demo held-out expectations ----
    pooled_p: list[float] = []
    pooled_y: list[float] = []
    per_demo_auc: list[tuple[str, float, int]] = []
    loo_p: dict[str, np.ndarray | None] = {}
    for h in hashes:
        y_h = labels[h]
        n = int(len(y_h))
        others = [h2 for h2 in hashes if h2 != h]
        entry_ok = False
        if n >= _MIN_HELDOUT and others and 0 < y_h.mean() < 1:
            X_train = np.vstack([feats[h2] for h2 in others])
            y_train = np.concatenate([labels[h2] for h2 in others])
            if len(np.unique(y_train)) == 2:
                theta = _fit_logistic(X_train, y_train)
                p_h = _predict(feats[h], theta)
                loo_p[h] = p_h
                pooled_p.extend(float(v) for v in p_h)
                pooled_y.extend(float(v) for v in y_h)
                per_demo_auc.append((h, _auc(p_h, y_h), n))
                entry_ok = True
        if not entry_ok:
            loo_p[h] = None

    model_block: dict = {"n_features": n_feat, "auc": None, "brier": None,
                         "calibration": None, "n_demos_evaluated": len(per_demo_auc)}
    if pooled_p:
        P = np.array(pooled_p)
        Y = np.array(pooled_y)
        n_total = sum(n for _, _, n in per_demo_auc)
        model_block = {
            "n_features": n_feat,
            "weighted_auc": round(sum(a * n for _, a, n in per_demo_auc) / n_total, 3)
            if n_total else None,
            "pooled_auc": round(_auc(P, Y), 3),
            "brier": round(brier_score(P, Y), 4),
            "calibration": decile_calibration(P, Y),
            "n_demos_evaluated": len(per_demo_auc),
        }

    # ---- per-player board over judged duels ----
    players: dict[str, dict] = {}
    duels_total = 0
    excluded_totals: dict[str, int] = {}
    for h in hashes:
        payload = per_demo[h]
        p_h = loo_p.get(h)
        for i, d in enumerate(payload["duels"]):
            duels_total += 1
            for role, sid in (("att", d["att"]), ("vic", d["vic"])):
                a = players.setdefault(sid, {
                    "steamid": sid, "name": payload["roster"].get(sid, sid),
                    "n": 0, "wins": 0, "n_exp": 0, "exp_p_sum": 0.0,
                })
                a["n"] += 1
                mine = d["y"] if role == "att" else 1 - d["y"]
                a["wins"] += int(mine)
                if p_h is not None:
                    pv = float(p_h[i])
                    mine_p = pv if role == "att" else 1.0 - pv
                    a["n_exp"] += 1
                    a["exp_p_sum"] += mine_p
        for k, v in (payload.get("excluded") or {}).items():
            excluded_totals[k] = excluded_totals.get(k, 0) + int(v)

    rows_out = []
    for a in players.values():
        n = a["n"]
        wr = a["wins"] / n if n else 0.0
        lo, hi = wilson_interval(a["wins"], n) if n else (0.0, 0.0)
        expected = a["exp_p_sum"] / a["n_exp"] if a["n_exp"] else None
        # 超预期差 on the expectation subset (context-adjusted duel skill);
        # EB shrink toward 0 is DISPLAY-ONLY (raw stays the main value)
        if expected is not None and a["n_exp"]:
            actual_exp = a["wins"] / a["n_exp"] if a["n_exp"] else 0.0
            diff = actual_exp - expected
            shrunk = (a["n_exp"] * diff) / (a["n_exp"] + _K_EVENT)
        else:
            diff = shrunk = None
        rows_out.append({
            "steamid": a["steamid"], "name": a["name"],
            "n": n, "wins": a["wins"],
            "win_rate": round(wr, 3),
            "conf": {"lo": round(lo, 3), "hi": round(hi, 3), "n": n,
                     "gated": n < DUEL_GATE_N},
            "n_exp": a["n_exp"],
            "expected_rate": round(expected, 3) if expected is not None else None,
            "diff": round(diff, 3) if diff is not None else None,
            "diff_shrunk": round(shrunk, 3) if shrunk is not None else None,
        })
    rows_out.sort(key=lambda r: -(r["n"]))

    note = (f"跨场留一对枪模型：{len(per_demo_auc)}/{len(hashes)} 场可评 · "
            f"加权 AUC {model_block['weighted_auc']:.2f}"
            if model_block.get("weighted_auc") is not None
            else "对枪模型：样本尚不可评（每场判定样本需 ≥12 且两类齐全）")
    return {
        "players": rows_out,
        "duels_total": duels_total,
        "n_demos": len(hashes),
        "excluded_totals": excluded_totals,
        "model": model_block,
        "gate_n": DUEL_GATE_N,
        "note": note,
        "notes": {
            "sample_def": "每回合每对敌对玩家首次伤害建一条（aim_science engagement 同源）",
            "label_def": "先死者归谁；没死/同亡/第三方打断/超 15s 不判定",
            "diff_def": "超预期差 = 实际对枪胜率 − 模型期望（同批样本）；模型已吸收距离/武器/血甲/预瞄/被闪等场景优势，剩下的就是'比预期更能打'；括号内为 EB 收缩展示值（k=32）",
            "boundaries": "无地图几何 → 无视线遮挡判定（被偷≈受击方视线夹角）；期望值来自跨场留一模型（自己不在训练集）",
        },
        "model_version": "duel-v1",
    }


def duel_report() -> dict:
    """Merged duel-model report (memoized, single-flight)."""
    global _report
    if _report is None:
        _scan_all()  # warm shards BEFORE the lock (X4 lesson)
        with _lock:
            if _report is None:
                _report = _build()
    return _report


def duel_peek() -> dict | None:
    """Read-only view of the warm memo (never triggers a cold scan)."""
    return _report


def duel_for(player_sid: str) -> dict | None:
    """One player's 对枪实力 row (+ report context) from the warm memo.

    Returns None when the memo is cold or the player has no judged duels —
    the route distinguishes via duel_peek() first (503 contract)."""
    report = _report
    if report is None:
        return None
    row = next((r for r in report["players"] if r["steamid"] == player_sid), None)
    if row is None:
        return None
    return {"player": row,
            "model": report["model"],
            "notes": report["notes"],
            "gate_n": report["gate_n"]}
