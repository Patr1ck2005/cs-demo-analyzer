"""Round win probability (Phase V1 胜势曲线).

Event-driven per-round win probability for one side, from a numpy logistic
model over compact round-state features:

  alive_diff        kills so far this round (attacker-side perspective):
                    (my_deaths_inflicted - my_losses) → alive advantage
  buy_diff          buy-quality difference (eco=0 / force=0.5 / full=1)
  equip_diff        round equipment value difference (normalized)
  planted           bomb planted (T-side only) and time since plant
  side              T attacking (1) or CT (0)

The model trains on the demo itself (LOO across matches happens at the web
layer); every probability is paired with a bootstrap confidence band. With
the current 24-demo library this is a *method preview*: the page labels the
sample size, and all numbers re-fit automatically as demos accumulate.

Pure numpy (no sklearn) per the dependency discipline.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.economy import EconomyResult
from cs_analyzer.analysis.util import clean_sid
from cs_analyzer.model.parsed_demo import ParsedDemo

N_FEATURES = 5


class RoundState(BaseModel):
    """One snapshot of a round (at each kill / plant / round end)."""
    round: int
    tick: int
    side: str  # perspective side ("T" | "CT")
    alive_diff: int
    buy_diff: float
    equip_diff: float
    planted: int
    p_win: float = 0.0
    p_lo: float = 0.0
    p_hi: float = 0.0
    outcome: int = 0  # 1 if this side won the round (label, train only)


class WinProbabilityResult(AnalysisResult):
    rounds: list[list[RoundState]] = Field(default_factory=list)  # per round, per snapshot
    model_auc: float = 0.0
    n_train_rounds: int = 0
    sample_note: str = ""


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
        i = j + 1
    pos = y == 1
    n_pos = int(pos.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


@register_module
class WinProbabilityModule(AnalysisModule):
    name = "win_probability"
    requires = ("economy",)

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        eco = ctx.require("economy")
        assert isinstance(eco, EconomyResult)
        rounds = demo.regular_rounds
        deaths = demo.events.get("player_death")
        plants = demo.events.get("bomb_planted")
        if not rounds:
            return WinProbabilityResult(module=self.name, demo_hash=demo.metadata.demo_hash)

        # ---- economy lookup: (round, side) -> buy tier value ----
        buy_val: dict[tuple[int, str], float] = {}
        equip: dict[tuple[int, str], float] = {}
        for r in eco.rounds:
            buy_val[(r.round, r.side)] = {"eco": 0.0, "force": 0.5, "full": 1.0}.get(r.buy, 0.5)
            equip[(r.round, r.side)] = r.avg_spend

        # ---- kills per round with side attribution (swap-safe) ----
        sides = _round_sides(demo)
        deaths_by_round: dict[int, list] = defaultdict(list)
        if deaths is not None and not deaths.empty:
            ddf = deaths[["tick", "attacker_steamid", "user_steamid"]].copy()
            ddf["attacker_steamid"] = ddf["attacker_steamid"].map(clean_sid)
            ddf["user_steamid"] = ddf["user_steamid"].map(clean_sid)
            for row in ddf.itertuples(index=False):
                deaths_by_round[_round_of(row.tick, rounds)].append(row)

        plant_tick: dict[int, int] = {}
        if plants is not None and not plants.empty and "tick" in plants.columns:
            for row in plants.itertuples(index=False):
                plant_tick[_round_of(int(row.tick), rounds)] = int(row.tick)

        # ---- build per-round snapshot series from the T-side perspective ----
        # (perspective flips per snapshot via `side`; symmetric features)
        snapshots: list[RoundState] = []
        labels: list[int] = []
        for rnd in rounds:
            my_side, opp_side = "T", "CT"
            winner = getattr(rnd, "winner_side", "")
            won = 1 if winner == my_side else 0
            kills = deaths_by_round.get(rnd.number, [])
            events: list[tuple[int, int]] = []  # (tick, alive_diff_delta)
            for k in kills:
                k_side = sides.get(rnd.number, {}).get(k.attacker_steamid)
                v_side = sides.get(rnd.number, {}).get(k.user_steamid)
                if k_side == my_side and v_side == opp_side:
                    events.append((int(k.tick), 1))
                elif v_side == my_side and k_side == opp_side:
                    events.append((int(k.tick), -1))
            events.sort()
            planted_at = plant_tick.get(rnd.number)
            ticks_at = [rnd.start_tick] + [e[0] for e in events]
            if planted_at and rnd.start_tick < planted_at < rnd.end_tick:
                ticks_at.append(planted_at)
            ticks_at.append(rnd.end_tick)
            ticks_at = sorted(set(t for t in ticks_at if rnd.start_tick <= t <= rnd.end_tick))

            alive = 0
            prev_tick = rnd.start_tick
            for t in ticks_at:
                for (et, delta) in events:
                    if et <= t and et > prev_tick:
                        alive += delta
                prev_tick = t
                planted = 1 if (planted_at and t >= planted_at) else 0
                bv = buy_val.get((rnd.number, my_side), 0.5)
                ov = buy_val.get((rnd.number, opp_side), 0.5)
                ev = equip.get((rnd.number, my_side), 0.0)
                ovq = equip.get((rnd.number, opp_side), 0.0)
                snapshots.append(RoundState(
                    round=rnd.number, tick=t, side=my_side,
                    alive_diff=alive, buy_diff=bv - ov,
                    equip_diff=(ev - ovq) / 10000.0,
                    planted=planted, outcome=won,
                ))
                labels.append(won)

        # ---- train (this demo) + predict with bootstrap band ----
        X = np.array([[s.alive_diff, s.buy_diff, s.equip_diff, s.planted, 1]
                      for s in snapshots], dtype=float)
        y = np.array(labels, dtype=float)
        note = ""
        if len(y) >= 12 and 0 < y.mean() < 1:
            theta = _fit_logistic(X, y)
            p_all = _predict(X, theta)
            # in-sample AUC (LOO across matches happens at web aggregation)
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
            note = (f"单场拟合：{len(y)} 个回合快照 · AUC {auc:.2f}（样本参考）"
                    f" · 阴影=80% bootstrap 置信带")
            return WinProbabilityResult(
                module=self.name, demo_hash=demo.metadata.demo_hash,
                rounds=_group_by_round(snapshots), model_auc=round(auc, 3),
                n_train_rounds=len(y), sample_note=note,
            )
        note = f"样本不足（{len(y)} 个快照）——需要更多 demo 才能拟合"
        return WinProbabilityResult(
            module=self.name, demo_hash=demo.metadata.demo_hash,
            rounds=_group_by_round(snapshots), model_auc=0.5,
            n_train_rounds=len(y), sample_note=note,
        )


def _group_by_round(snaps: list[RoundState]) -> list[list[RoundState]]:
    by: dict[int, list[RoundState]] = defaultdict(list)
    for s in snaps:
        by[s.round].append(s)
    return [by[k] for k in sorted(by)]


def _round_of(tick: int, rounds: list) -> int:
    for r in rounds:
        if r.start_tick <= tick <= r.end_tick:
            return r.number
    return rounds[0].number if rounds else 0


def _round_sides(demo: ParsedDemo) -> dict[int, dict[str, str]]:
    from cs_analyzer.analysis.util import round_player_sides

    return round_player_sides(demo)
