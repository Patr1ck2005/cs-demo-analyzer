"""Round win probability (Phase V1 胜势曲线 → V2 研究迭代 Round 1).

Event-driven per-round win probability, from a numpy logistic model over
compact round-state features. V2 (docs/research-ledger.md Round 1) upgrades
the V1 4-feature model along the weaknesses recorded in the baseline:

  alive_diff        kills-so-far difference (kept — strong V1 signal)
  buy_diff          buy-quality difference (eco=0 / force=0.5 / full=1)
  equip_diff        round equipment value difference (normalized /10000)
  planted           bomb planted (perspective side attacking)
  plant_sec         seconds since the plant (0 when not planted)
  elapsed_sec       seconds since round start, CAPPED at the nominal round
                    time (115s regular / 20s OT) — the measured end tick
                    would leak the outcome
  hp_diff           total HP of alive players, mine minus theirs (ticks
                    `health`; 0 when tick data lacks the column)
  awp_diff          alive players who BOUGHT an AWP this round, diff
                    (purchase-log based; picked-up AWPs not counted)
  util_diff         utility remaining (bought − detonated so far), diff
  rating_diff       sum of this demo's Rating21 over ALIVE players, diff
  side              T=1 / CT=0 — V2 builds snapshots from BOTH perspectives
                    (V1's `side` was constant: it could not learn the
                    CT/T asymmetry at all)
  alive_x_planted   alive_diff × planted (post-plant man-advantage compound)

The model trains on the demo itself for the in-sample preview; the honest
cross-match curve is the web layer's leave-one-out fit (web/winprob_loo.py),
which now also serves the per-demo OOS curve when the memo is warm.

Pure numpy (no sklearn) per the dependency discipline.
"""
from __future__ import annotations

import bisect
from collections import defaultdict

import numpy as np
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.economy import EconomyResult, build_purchase_log
from cs_analyzer.analysis.ratings21 import Ratings21Result
from cs_analyzer.analysis.util import clean_sid
from cs_analyzer.model.parsed_demo import ParsedDemo

N_FEATURES = 12

#: Fixed feature order — the winloo shard payload rows follow this exactly.
FEATURE_NAMES = (
    "alive_diff", "buy_diff", "equip_diff", "planted", "plant_sec",
    "elapsed_sec", "hp_diff", "awp_diff", "util_diff",
    "rating_diff", "side", "alive_x_planted",
)

# Nominal round-time caps for elapsed_sec (anti-leakage: the measured
# end_tick would leak the outcome — a long-measured round correlates with
# "the round was contested to the end"). OT rounds play 20s clocks.
REGULAR_ROUND_SEC = 115.0
OVERTIME_ROUND_SEC = 20.0


class RoundState(BaseModel):
    """One snapshot of a round (at each kill / plant / round end)."""
    round: int
    tick: int
    side: str  # perspective side ("T" | "CT")
    alive_diff: int = 0
    buy_diff: float = 0.0
    equip_diff: float = 0.0
    planted: int = 0
    # V2 features
    alive_mine: int = 0
    alive_opp: int = 0
    plant_sec: float = 0.0
    elapsed_sec: float = 0.0
    hp_diff: float = 0.0
    awp_diff: int = 0
    util_diff: int = 0
    rating_diff: float = 0.0
    # model outputs + label
    p_win: float = 0.0
    p_lo: float = 0.0
    p_hi: float = 0.0
    outcome: int = 0  # 1 if this side won the round (label, train only)


class WinProbabilityResult(AnalysisResult):
    rounds: list[list[RoundState]] = Field(default_factory=list)  # T-view, per round, per snapshot (page curve)
    snapshots_all: list[RoundState] = Field(default_factory=list)  # both perspectives (training + shard payload)
    alive_keys: list[list] = Field(default_factory=list)  # H-B rekey rows [round, tick, side01, mine_sids, opp_sids]
    model_auc: float = 0.0
    n_train_rounds: int = 0
    sample_note: str = ""
    model_version: str = "V2"
    feature_names: list[str] = Field(default_factory=lambda: list(FEATURE_NAMES))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _standardize(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-score per column (avoid unnormalized feature scales — equip_diff in
    the thousands was drowning the gradient). Returns (Xz, mean, std)."""
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return (X - mu) / sd, mu, sd


def _fit_logistic(X: np.ndarray, y: np.ndarray, iters: int = 600, lr: float = 0.1,
                  l2: float = 0.01) -> np.ndarray:
    """Plain gradient-descent logistic regression with L2 (no sklearn).

    Returns theta with the LAST element = intercept; features are
    standardized internally so lr works across any raw scale.
    """
    Xz, mu, sd = _standardize(X)
    n, k = Xz.shape
    w = np.zeros(k)
    b = 0.0
    for _ in range(iters):
        z = Xz @ w + b
        p = _sigmoid(z)
        gw = Xz.T @ (p - y) / n + l2 * w
        gb = float(np.mean(p - y))
        w -= lr * gw
        b -= lr * gb
    # fold standardization back into raw-feature space: z = X @ (w/sd) + (b - mu·w/sd)
    return np.concatenate([w / sd, [b - float(mu @ (w / sd))]])


def _predict(X: np.ndarray, theta: np.ndarray) -> np.ndarray:
    return _sigmoid(X @ theta[:-1] + theta[-1])


def _auc(p: np.ndarray, y: np.ndarray) -> float:
    """Rank-based AUC (handles ties via average ranks)."""
    order = np.argsort(p)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # average ranks for ties
    sorted_p = p[order]
    i = 0
    while i < len(sorted_p):
        j = i
        while j + 1 < len(sorted_p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1  # BUGFIX(V2): step past the tie group — dropping this
        # line made any tied prediction an infinite loop (pytest hang root).
    pos = y == 1
    n_pos = int(pos.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


# ------------------------------------------------------------------ R1 conf
# Probability-forecast metrics shared by the LOO memo (web/winprob_loo.py)
# and scripts/research_eval.py — single source of truth for the protocol.


def brier_score(p: np.ndarray, y: np.ndarray) -> float:
    """Mean squared error of probability forecasts (lower = better)."""
    if len(p) == 0:
        return 0.0
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def decile_calibration(p: np.ndarray, y: np.ndarray) -> list[dict]:
    """Fixed-width 10% calibration bins (stable across model versions —
    quantile bins would drift with the model and hide calibration shifts)."""
    P = np.asarray(p, dtype=float)
    Y = np.asarray(y, dtype=float)
    out: list[dict] = []
    for b in range(10):
        lo, hi = b / 10.0, (b + 1) / 10.0
        m = (P >= lo) & ((P < hi) if b < 9 else (P <= hi))
        n = int(m.sum())
        out.append({
            "bin": f"[{lo:.0%},{hi:.0%}]" if b < 9 else f"[{lo:.0%},100%]",
            "n": n,
            "mean_pred": round(float(P[m].mean()), 4) if n else None,
            "obs_rate": round(float(Y[m].mean()), 4) if n else None,
        })
    return out


def _feature_row(s: RoundState) -> list[float]:
    """Shard/model feature vector in FEATURE_NAMES order."""
    return [float(s.alive_diff), float(s.buy_diff), float(s.equip_diff),
            float(s.planted), float(s.plant_sec), float(s.elapsed_sec),
            float(s.hp_diff), float(s.awp_diff), float(s.util_diff),
            float(s.rating_diff), 1.0 if s.side == "T" else 0.0,
            float(s.alive_diff) * float(s.planted)]


# ------------------------------------------------------------------ extractor

class _TickState:
    """Per-player (tick -> alive/health) lookups over the sorted tick table.

    Ticks carry `health` (0 while dead), so side HP sums need no alive
    filtering; the alive flag still drives count/rating features.
    """

    def __init__(self, ticks) -> None:
        self.usable = False
        cols = {"steamid", "tick", "is_alive", "health"}
        if ticks is None or ticks.empty or not cols.issubset(set(ticks.columns)):
            return
        t = ticks[["steamid", "tick", "is_alive", "health"]].sort_values(
            ["steamid", "tick"], kind="stable")
        sid = t["steamid"].to_numpy()
        self.tick_arr = t["tick"].to_numpy(dtype=np.int64)
        self.alive_arr = t["is_alive"].to_numpy(dtype=float)
        self.hp_arr = t["health"].to_numpy(dtype=float)
        bounds = np.flatnonzero(np.r_[True, sid[1:] != sid[:-1]])
        edges = np.r_[bounds, len(sid)]
        self.runs = {str(sid[b]): (int(b), int(e))
                     for b, e in zip(bounds, edges[1:])}
        self.usable = True

    def state(self, sid: str, tick: int) -> tuple[bool, float] | None:
        """(alive, health) at `tick`, or None when the player has no rows."""
        run = self.runs.get(sid)
        if run is None:
            return None
        i0, i1 = run
        i = i0 + int(np.searchsorted(self.tick_arr[i0:i1], tick, side="right")) - 1
        if i < i0:
            return None
        return (self.alive_arr[i] > 0.5, float(self.hp_arr[i]))


@register_module
class WinProbabilityModule(AnalysisModule):
    name = "win_probability"
    requires = ("economy", "ratings21")

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        eco = ctx.require("economy")
        assert isinstance(eco, EconomyResult)
        r21 = ctx.require("ratings21")
        assert isinstance(r21, Ratings21Result)
        rounds = demo.regular_rounds
        deaths = demo.events.get("player_death")
        plants = demo.events.get("bomb_planted")
        if not rounds:
            return WinProbabilityResult(module=self.name, demo_hash=demo.metadata.demo_hash)

        tick_rate = float(demo.metadata.tick_rate or 64)

        # ---- economy lookup: (round, side) -> buy tier value ----
        buy_val: dict[tuple[int, str], float] = {}
        equip: dict[tuple[int, str], float] = {}
        for r in eco.rounds:
            buy_val[(r.round, r.side)] = {"eco": 0.0, "force": 0.5, "full": 1.0}.get(r.buy, 0.5)
            equip[(r.round, r.side)] = r.avg_spend

        sides = _round_sides(demo)
        ts = _TickState(demo.ticks)

        # ---- AWP buyers + utility purchases from the shared purchase log ----
        purchase_log = build_purchase_log(demo)
        awp_buyers: dict[int, set[str]] = defaultdict(set)
        nades_bought: dict[tuple[int, str], int] = defaultdict(int)
        for rnd_no, players in purchase_log.items():
            per_side: dict[str, int] = defaultdict(int)
            for sid, bucket in players.items():
                if "awp" in bucket.get("weapons", []):
                    awp_buyers[rnd_no].add(sid)
                per_side[sides.get(rnd_no, {}).get(sid, "")] += bucket.get("nades", 0)
            for side, n in per_side.items():
                if side in ("T", "CT"):
                    nades_bought[(rnd_no, side)] = n

        # ---- utility detonations per (round, side), sorted tick lists ----
        # smoke/flash/he count once; fire grenades: molotov_detonate marks
        # them (inferno_startburn is the fallback for broadcasts that only
        # emit it — utility_effect precedent). Never both (double count).
        det_ticks: dict[tuple[int, str], list[int]] = defaultdict(list)
        for kind in ("smokegrenade_detonate", "flashbang_detonate",
                     "hegrenade_detonate", "molotov_detonate"):
            df = demo.events.get(kind)
            if df is None or df.empty:
                continue
            for row in df.itertuples(index=False):
                t = int(getattr(row, "tick", 0) or 0)
                rn = _round_of(t, rounds)
                sid = clean_sid(getattr(row, "user_steamid", "") or "")
                side = sides.get(rn, {}).get(sid, "")
                if side in ("T", "CT"):
                    det_ticks[(rn, side)].append(t)
        fire_events = demo.events.get("inferno_startburn")
        if demo.events.get("molotov_detonate") is not None and not demo.events["molotov_detonate"].empty:
            fire_events = None  # molotov already counted above
        if fire_events is not None and not fire_events.empty:
            for row in fire_events.itertuples(index=False):
                t = int(getattr(row, "tick", 0) or 0)
                rn = _round_of(t, rounds)
                sid = clean_sid(getattr(row, "user_steamid", "") or "")
                side = sides.get(rn, {}).get(sid, "")
                if side in ("T", "CT"):
                    det_ticks[(rn, side)].append(t)
        for v in det_ticks.values():
            v.sort()

        # ---- deaths per round with victim-side attribution (swap-safe) ----
        deaths_by_round: dict[int, list] = defaultdict(list)
        if deaths is not None and not deaths.empty:
            ddf = deaths[["tick", "attacker_steamid", "user_steamid"]].copy()
            ddf["attacker_steamid"] = ddf["attacker_steamid"].map(clean_sid)
            ddf["user_steamid"] = ddf["user_steamid"].map(clean_sid)
            for row in ddf.itertuples(index=False):
                rn = _round_of(int(row.tick), rounds)
                if rn == 0:
                    continue  # warmup / post-match rows must not leak into R1
                deaths_by_round[rn].append(row)

        plant_tick: dict[int, int] = {}
        if plants is not None and not plants.empty and "tick" in plants.columns:
            for row in plants.itertuples(index=False):
                rn = _round_of(int(row.tick), rounds)
                if rn != 0:
                    plant_tick[rn] = int(row.tick)

        rating_of = {p.steamid: p.Rating21 for p in r21.players}

        # ---- per-round snapshot series from BOTH perspectives ----
        snapshots: list[RoundState] = []
        alive_keys: list[list] = []  # H-B rekey: [round, tick, side01, mine, opp]
        for rnd in rounds:
            winner = getattr(rnd, "winner_side", "")
            if winner not in ("T", "CT"):
                continue  # warmup/knife rounds have no label to learn from
            side_sids: dict[str, list[str]] = {"T": [], "CT": []}
            for sid, sd in sides.get(rnd.number, {}).items():
                if sd in ("T", "CT"):
                    side_sids[sd].append(sid)

            # victim deaths sorted per side (delta-mode alive reconstruction)
            round_deaths: dict[str, list[tuple[int, str]]] = {"T": [], "CT": []}
            for k in deaths_by_round.get(rnd.number, []):
                v_side = sides.get(rnd.number, {}).get(k.user_steamid)
                if v_side in ("T", "CT"):
                    round_deaths[v_side].append((int(k.tick), k.user_steamid))
            for v in round_deaths.values():
                v.sort()
            death_ticks = {side: [tk for tk, _ in round_deaths[side]]
                           for side in ("T", "CT")}

            planted_at = plant_tick.get(rnd.number)
            cap = OVERTIME_ROUND_SEC if getattr(rnd, "is_overtime", False) else REGULAR_ROUND_SEC
            ticks_at = {rnd.start_tick, rnd.end_tick}
            for side in ("T", "CT"):
                ticks_at.update(death_ticks[side])
            if planted_at and rnd.start_tick < planted_at < rnd.end_tick:
                ticks_at.add(planted_at)
            ticks_at = sorted(t for t in ticks_at if rnd.start_tick <= t <= rnd.end_tick)
            perspectives = ("T", "CT") if ts.usable else ("T",)

            for t in ticks_at:
                # per-tick state computed once, reused by both perspectives
                alive = {"T": 0, "CT": 0}
                hp = {"T": 0.0, "CT": 0.0}
                awp = {"T": 0, "CT": 0}
                rtg = {"T": 0.0, "CT": 0.0}
                alive_sids = {"T": [], "CT": []}  # H-B: career-rating rekey
                if ts.usable:
                    for side in ("T", "CT"):
                        for sid in side_sids[side]:
                            st = ts.state(sid, t)
                            if st is None or not st[0]:
                                continue
                            alive[side] += 1
                            alive_sids[side].append(sid)
                            hp[side] += st[1]
                            if sid in awp_buyers.get(rnd.number, set()):
                                awp[side] += 1
                            rtg[side] += rating_of.get(sid, 0.0)
                else:
                    for side in ("T", "CT"):
                        dead_sids = {sid for tk, sid in round_deaths[side] if tk <= t}
                        alive[side] = len(side_sids[side]) - len(dead_sids)
                        alive_sids[side] = [s for s in side_sids[side]
                                            if s not in dead_sids]
                        for sid in side_sids[side]:
                            if sid in awp_buyers.get(rnd.number, set()):
                                awp[side] += 1
                            rtg[side] += rating_of.get(sid, 0.0)

                for my_side in perspectives:
                    opp_side = "CT" if my_side == "T" else "T"
                    planted = 1 if (planted_at and t >= planted_at) else 0
                    util_mine = (nades_bought.get((rnd.number, my_side), 0)
                                 - bisect.bisect_right(det_ticks.get((rnd.number, my_side), []), t))
                    util_opp = (nades_bought.get((rnd.number, opp_side), 0)
                                - bisect.bisect_right(det_ticks.get((rnd.number, opp_side), []), t))
                    bv = buy_val.get((rnd.number, my_side), 0.5)
                    ov = buy_val.get((rnd.number, opp_side), 0.5)
                    ev = equip.get((rnd.number, my_side), 0.0)
                    ovq = equip.get((rnd.number, opp_side), 0.0)
                    snapshots.append(RoundState(
                        round=rnd.number, tick=t, side=my_side,
                        alive_diff=alive[my_side] - alive[opp_side],
                        buy_diff=bv - ov,
                        equip_diff=(ev - ovq) / 10000.0,
                        planted=planted,
                        alive_mine=alive[my_side], alive_opp=alive[opp_side],
                        plant_sec=((t - planted_at) / tick_rate) if planted else 0.0,
                        elapsed_sec=min((t - rnd.start_tick) / tick_rate, cap),
                        hp_diff=hp[my_side] - hp[opp_side],
                        awp_diff=awp[my_side] - awp[opp_side],
                        util_diff=util_mine - util_opp,
                        rating_diff=rtg[my_side] - rtg[opp_side],
                        outcome=1 if winner == my_side else 0,
                    ))
                    # H-B: alive-roster key for the merge-layer career-rating
                    # rekey (kept OUT of the row vector — 12 features stay)
                    alive_keys.append([rnd.number, t,
                                       1 if my_side == "T" else 0,
                                       "|".join(alive_sids[my_side]),
                                       "|".join(alive_sids[opp_side])])

        # ---- train (this demo) + predict with bootstrap band ----
        X = np.array([_feature_row(s) for s in snapshots], dtype=float)
        y = np.array([s.outcome for s in snapshots], dtype=float)
        note = (f"V2 双侧视角 · {len(y)} 个回合快照"
                if ts.usable else
                f"V2 · {len(y)} 个快照（tick 数据不完整：HP/AWP/存活质量特征部分缺省）")
        if len(y) >= 12 and 0 < y.mean() < 1:
            theta = _fit_logistic(X, y)
            p_all = _predict(X, theta)
            auc = _auc(p_all, y)
            rng = np.random.default_rng(42)
            boots = []
            for _ in range(60):
                idx = rng.integers(0, len(y), len(y))
                if len(np.unique(y[idx])) < 2:
                    continue
                try:
                    bt = _fit_logistic(X[idx], y[idx], iters=120)
                    boots.append(_predict(X, bt))
                except Exception:  # noqa: BLE001
                    continue
            if boots:
                B = np.stack(boots)
                lo = np.percentile(B, 10, axis=0)
                hi = np.percentile(B, 90, axis=0)
            else:
                lo = np.full(len(y), 0.3)
                hi = np.full(len(y), 0.7)
            for s, pv, lov, hiv in zip(snapshots, p_all, lo, hi):
                s.p_win = round(float(pv), 3)
                s.p_lo = round(float(lov), 3)
                s.p_hi = round(float(hiv), 3)
            note += f" · 单场拟合 AUC {auc:.2f}（样本参考，页面曲线优先用跨场留一）"
            return WinProbabilityResult(
                module=self.name, demo_hash=demo.metadata.demo_hash,
                rounds=_group_by_round(snapshots), snapshots_all=snapshots,
                alive_keys=alive_keys,
                model_auc=round(auc, 3), n_train_rounds=len(y), sample_note=note,
            )
        note += " —— 样本不足（需要更多 demo 才能拟合）"
        return WinProbabilityResult(
            module=self.name, demo_hash=demo.metadata.demo_hash,
            rounds=_group_by_round(snapshots), snapshots_all=snapshots,
            alive_keys=alive_keys,
            model_auc=0.5, n_train_rounds=len(y), sample_note=note,
        )


def _group_by_round(snaps: list[RoundState]) -> list[list[RoundState]]:
    """Page curve: T-view snapshots only, grouped by round (V1 semantics)."""
    by: dict[int, list[RoundState]] = defaultdict(list)
    for s in snaps:
        if s.side == "T":
            by[s.round].append(s)
    return [by[k] for k in sorted(by)]


def _round_of(tick: int, rounds: list) -> int:
    """Round number containing `tick`, 0 when outside every regular round
    (warmup / post-match events must not leak into round 1)."""
    for r in rounds:
        if r.start_tick <= tick <= r.end_tick:
            return r.number
    return 0


def _round_sides(demo: ParsedDemo) -> dict[int, dict[str, str]]:
    from cs_analyzer.analysis.util import round_player_sides

    return round_player_sides(demo)
