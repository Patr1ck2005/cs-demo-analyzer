"""Statistical rigor toolkit (Phase R1, 统计严谨基建).

Project principle: “凡是人与人之间对比的指标，一定要排除打得多=数据高”
(HANDOFF §1). Until now that principle was enforced at the metric-design
layer (per-round / per-demo denominators). R1 adds the *inference* layer:

- **Wilson score interval** for rates/proportions: an honest interval even
  at tiny n (the normal approximation collapses there). A 1/1 (100%) sample
  reports [20.7%, 100%] instead of "100%" — the “1局0胜” lesson,
  institutionalized.
- **Empirical-Bayes linear shrinkage** for per-unit means (per-demo / per-
  round values): ``(n·x + k·μ) / (n + k)`` where μ is the pool mean of the
  board and k is a pseudo-count. Players with few samples are pulled toward
  the pool; players with many samples keep their raw value.
- `attach_conf` decorates leaderboard rows in-place with a ``conf`` dict:
  ``{"lo": float, "hi": float, "n": int, "gated": bool}``.

Design rules:
- Pure functions, numpy only, zero new dependencies.
- Rows keep their raw value; ``conf`` is *additive* metadata. Gating means
  "show greyed with the actual n", never "hide" (V2 EV-table precedent).
- The two shrinkage strengths encode denominator type: demo-level boards
  k=4, round-level boards k=64. Constants live here so call sites stay
  honest and tunable in one place.
"""
from __future__ import annotations

import math

# Empirical-Bayes pseudo-counts. k is "how many samples of prior-strength
# to pretend the pool contributes": 4 demos for per-demo boards, 64 rounds
# for per-round boards (≈ one demo of evidence), 32 events for per-event
# means (≈ two demos of kills/throws — event means converge fast enough
# that a heavier pull would erase real signal at library scale).
K_PER_DEMO = 4
K_PER_ROUND = 64
K_PER_EVENT = 32

# Default gate: below this n the row renders greyed (still visible, with n).
DEFAULT_GATE_N = 3

Z95 = 1.959963984540054  # two-sided 95%


def wilson_interval(successes: float, n: float, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Returns (lo, hi), clamped to [0, 1]. Stable at n=0 (returns (0.0, 0.0)) —
    callers gate those rows anyway.
    """
    n = float(n)
    if n <= 0:
        return (0.0, 0.0)
    p = max(0.0, min(1.0, successes / n))
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    spread = (z / denom) * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return (max(0.0, center - spread), min(1.0, center + spread))


def shrunk_mean(x: float, n: float, prior: float, k: float = K_PER_DEMO) -> float:
    """Linear empirical-Bayes shrinkage of a per-unit mean toward `prior`.

    n=0 -> prior. As n grows the estimate converges to the raw x. Never
    extrapolates beyond the data (unlike multiplicative shrinkage on
    negative/deviant values).
    """
    n = float(n)
    if n <= 0:
        return float(prior)
    return float((n * float(x) + k * float(prior)) / (n + k))


def attach_conf(
    rows: list[dict],
    value_key: str,
    n_key: str,
    kind: str = "rate",
    gate_n: int = DEFAULT_GATE_N,
    prior: float | None = None,
    k: float = K_PER_DEMO,
) -> list[dict]:
    """Attach ``conf`` to every row of a leaderboard, in place. Returns rows.

    kind="rate": value is a proportion; n is the number of Bernoulli trials.
      A row whose raw count column is absent may carry ``rate*n`` in
      ``value_key`` as a float — Wilson is computed from the implied count
      and the (rounded) implied count is what ``conf["n"]`` reports, so the
      interval stays honest either way.
    kind="mean": value is a per-unit mean; EB shrinkage toward `prior`
      (default: the weighted pool mean of the board). Adds ``shrunk`` to the
      row and keeps the raw value in the row (callers render raw in brackets,
      Y2 donor precedent: “14065.5$（共 496600$）”).
    """
    if not rows:
        return rows

    if kind == "mean":
        if prior is None:
            total_n = 0.0
            total_v = 0.0
            for r in rows:
                n = _f(r.get(n_key))
                if n > 0:
                    total_n += n
                    total_v += n * _f(r.get(value_key))
            prior = (total_v / total_n) if total_n > 0 else 0.0
        for r in rows:
            n = _f(r.get(n_key))
            raw = _f(r.get(value_key))
            s = shrunk_mean(raw, n, prior, k)
            r["shrunk"] = round(s, 4)
            r["conf"] = {
                "lo": round(min(raw, s), 4),
                "hi": round(max(raw, s), 4),
                "n": int(round(n)),
                "gated": n < gate_n,
            }
        return rows

    # kind == "rate"
    for r in rows:
        n = _f(r.get(n_key))
        p = _f(r.get(value_key))
        if n > 0 and not (0.0 <= p <= 1.0):
            # rate given as 0-100 or as a non-count-derived scale: normalize
            # by treating it as a percentage when in (1, 100].
            if 1.0 < p <= 100.0:
                p = p / 100.0
            else:
                p = max(0.0, min(1.0, p))
        implied = p * n if n > 0 else 0.0
        lo, hi = wilson_interval(implied, n)
        r["conf"] = {
            "lo": round(lo, 4),
            "hi": round(hi, 4),
            "n": int(round(n)),
            "gated": n < gate_n,
        }
    return rows


def _f(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if f != f else f  # NaN -> 0.0
