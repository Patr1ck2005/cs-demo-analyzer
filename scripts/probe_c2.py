"""C2 research probe: H-C1 impact sanity + H-C2 untraded-rate gates.

Offline script — builds the winloo memo + loss report over the real
library (scanning is fine here; U1 only constrains request paths).

Gates (口径 approved 2026-09-10):
  H-C1 G1 每事件视角一致性: median |d_T + d_CT| <= 0.05 over attributed
         single-death events (own-view model outputs are independent, so
         this measures perspective consistency, not exact mirror);
  H-C1 G2 方向性: winner-side total impact > loser-side in >= 70% demos;
  H-C1 G3 增量信息: Spearman(player total impact, Rating 2.1) in [0.3, 0.9];
  H-C2 G4 区分度: untraded-rate IQR >= 0.10 (players with >= 10 lost deaths);
  H-C2 G5 增量信息: |Spearman(rate, Rating 2.1)| < 0.7.

Writes output/research/probe_c2_<ts>.json. Exit 2 = any gate failed.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _rank(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        r = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _event_residuals(shard: dict, p_rows: list[float]) -> list[float]:
    """|d_T + d_CT| per attributed single-death event (perspective consistency)."""
    keys = shard.get("alive_keys") or []
    deaths_rows = shard.get("deaths") or []
    sides = shard.get("sides") or []
    pos = shard.get("positions") or []
    n = min(len(keys), len(p_rows), len(sides), len(pos), len(deaths_rows))
    seq: dict[tuple[str, int], list[int]] = {}
    for i in range(n):
        seq.setdefault((sides[i], int(pos[i][0])), []).append(i)
    delta: dict[tuple[str, int, int], float] = {}
    for (side, rn), idxs in seq.items():
        for a, b in zip(idxs, idxs[1:]):
            delta[(side, rn, int(pos[b][1]))] = p_rows[b] - p_rows[a]
    res: list[float] = []
    for (side, rn), idxs in seq.items():
        opp = "CT" if side == "T" else "T"
        for a, b in zip(idxs, idxs[1:]):
            ev = deaths_rows[b] or []
            if len(ev) != 1:
                continue
            m = delta.get((opp, rn, int(pos[b][1])))
            if m is None:
                continue
            res.append(abs((p_rows[b] - p_rows[a]) + m))
    return res


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    mid = s[len(s) // 2]
    return (s[len(s) // 2 - 1] + mid) / 2 if len(s) % 2 == 0 else mid


def _iqr(vals: list[float]) -> float | None:
    if len(vals) < 4:
        return None
    s = sorted(vals)
    n = len(s)

    def q(p: float) -> float:
        k = (n - 1) * p
        f = int(k)
        return s[f] + (s[min(f + 1, n - 1)] - s[f]) * (k - f)

    return q(0.75) - q(0.25)


def _r21(sid: str) -> float | None:
    from cs_analyzer.web.rating21_data import player_card

    card = player_card(sid)
    if card and card.get("rating21") is not None:
        return float(card["rating21"])
    return None


def main() -> int:
    from cs_analyzer.web import loss_data, winprob_loo
    from cs_analyzer.web.aggregation import aggregated

    t0 = time.time()
    memo = winprob_loo.loo_report()
    shards = winprob_loo._scan_all()
    agg = aggregated()
    scores = {d.demo_hash: (d.t_score, d.ct_score) for d in agg.demos}
    rep: dict = {"generated": datetime.now(timezone.utc).isoformat()}

    # ---- H-C1 gates ----
    residuals: list[float] = []
    per_demo_dir: list[bool] = []
    player_totals: dict[str, float] = {}
    for h, rows in (memo.get("impact") or {}).items():
        sh = shards.get(h)
        if sh is None:
            continue
        p_rows = (memo.get("oos_curves", {}).get(h, {}) or {}).get("p") or []
        residuals.extend(_event_residuals(sh, p_rows))
        # T-side roster straight from the shard's T-view alive rosters
        t_sids: set[str] = set()
        for k in sh.get("alive_keys") or []:
            if k[2] == 1 and k[3]:
                t_sids |= set(k[3].split("|"))
        t_sum = sum(v for sid, v in rows.items() if sid in t_sids)
        ct_sum = sum(rows.values()) - t_sum
        sc = scores.get(h)
        if sc is not None and sc[0] != sc[1]:
            win_sum = t_sum if sc[0] > sc[1] else ct_sum
            lose_sum = ct_sum if sc[0] > sc[1] else t_sum
            per_demo_dir.append(win_sum > lose_sum)
        for sid, v in rows.items():
            player_totals[sid] = player_totals.get(sid, 0.0) + v

    g1 = _median(residuals)
    g1_pass = g1 is not None and g1 <= 0.05
    g2_share = (sum(per_demo_dir) / len(per_demo_dir)) if per_demo_dir else None
    g2_pass = g2_share is not None and g2_share >= 0.70

    pairs = [(v, r) for sid, v in player_totals.items()
             if (r := _r21(sid)) is not None]
    g3 = _spearman([a for a, _ in pairs], [b for _, b in pairs])
    g3_pass = g3 is not None and 0.3 <= g3 <= 0.9
    rep["hc1"] = {
        "n_demos_with_impact": len(memo.get("impact") or {}),
        "n_events_consistency": len(residuals),
        "g1_consistency_median": None if g1 is None else round(g1, 4),
        "g1_pass": g1_pass,
        "g2_winner_share": None if g2_share is None else round(g2_share, 3),
        "n_demos_direction": len(per_demo_dir),
        "g2_pass": g2_pass,
        "g3_spearman_impact_r21": None if g3 is None else round(g3, 3),
        "n_players_g3": len(pairs),
        "g3_pass": g3_pass,
        "top10_by_total": [
            {"steamid": s, "total": round(v, 2), "r21": _r21(s)}
            for s, v in sorted(player_totals.items(), key=lambda kv: -kv[1])[:10]
        ],
    }

    # ---- H-C2 gates ----
    lrep = loss_data.loss_report()
    rates = [(p["steamid"], p["untraded_rate"])
             for p in lrep.get("players", [])
             if (p.get("lost_deaths") or 0) >= 10
             and p.get("untraded_rate") is not None]
    g4 = _iqr([r for _, r in rates])
    g4_pass = g4 is not None and g4 >= 0.10
    pairs2 = [(r, r21) for sid, r in rates if (r21 := _r21(sid)) is not None]
    g5 = _spearman([a for a, _ in pairs2], [b for _, b in pairs2])
    g5_pass = g5 is not None and abs(g5) < 0.7
    rep["hc2"] = {
        "n_players": len(rates),
        "g4_iqr": None if g4 is None else round(g4, 3),
        "g4_pass": g4_pass,
        "g5_spearman_rate_r21": None if g5 is None else round(g5, 3),
        "g5_pass": g5_pass,
    }

    gates_ok = all([g1_pass, g2_pass, g3_pass]) and all([g4_pass, g5_pass])
    rep["gates_ok"] = gates_ok

    out_dir = Path("output/research")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"probe_c2_{ts}.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    print(f"probe_c2: {out}")
    print(f"H-C1 G1 consistency median={rep['hc1']['g1_consistency_median']} "
          f"pass={g1_pass}")
    print(f"H-C1 G2 winner share={rep['hc1']['g2_winner_share']} pass={g2_pass}")
    print(f"H-C1 G3 spearman={rep['hc1']['g3_spearman_impact_r21']} pass={g3_pass}")
    print(f"H-C2 G4 IQR={rep['hc2']['g4_iqr']} pass={g4_pass}")
    print(f"H-C2 G5 spearman={rep['hc2']['g5_spearman_rate_r21']} pass={g5_pass}")
    print(f"GATES: {'PASS' if gates_ok else 'FAIL'} ({time.time() - t0:.1f}s)")
    return 0 if gates_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
