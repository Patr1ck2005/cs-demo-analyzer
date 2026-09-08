"""Opening route clustering (开局路线聚类, Phase F M8).

Per (side, round): resample each alive player's trajectory over the first
OPENING_SECONDS after freeze-end to N waypoints, average per team → one
polyline per round; cluster with a seeded numpy k-means (no sklearn — offline
constraint). Centroid routes render as ECharts lines over the radar PNG.
"""
from __future__ import annotations

import logging

import numpy as np
from pydantic import Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.replay.timeline import round_freeze_ends

logger = logging.getLogger(__name__)

OPENING_SECONDS = 25.0
N_POINTS = 10
K_CANDIDATES = (2, 3, 4)
SEED = 42


def resample_path(xs: np.ndarray, ys: np.ndarray, n: int = N_POINTS) -> np.ndarray | None:
    """Resample an (x,y) trajectory to n equidistant points by arc length."""
    if len(xs) < 2:
        return None
    d = np.hypot(np.diff(xs), np.diff(ys))
    s = np.concatenate([[0.0], np.cumsum(d)])
    total = s[-1]
    if not np.isfinite(total) or total <= 0:
        return None
    targets = np.linspace(0.0, total, n)
    out = np.empty((n, 2))
    for k, target in enumerate(targets):
        i = int(np.searchsorted(s, target, side="right")) - 1
        i = max(0, min(i, len(xs) - 2))
        seg = s[i + 1] - s[i]
        f = 0.0 if seg <= 0 else (target - s[i]) / seg
        out[k, 0] = xs[i] + (xs[i + 1] - xs[i]) * f
        out[k, 1] = ys[i] + (ys[i + 1] - ys[i]) * f
    return out


def kmeans(data: np.ndarray, k: int, seed: int = SEED, iters: int = 50) -> tuple[np.ndarray, np.ndarray, float]:
    """Deterministic k-means (seeded k-means++ init). Returns (centroids, labels, inertia)."""
    rng = np.random.default_rng(seed)
    n = len(data)
    # k-means++ init
    centroids = [data[rng.integers(n)]]
    for _ in range(1, k):
        d2 = np.min(((data[:, None, :] - np.array(centroids)[None, :, :]) ** 2).sum(-1), axis=1)
        probs = d2 / d2.sum() if d2.sum() > 0 else np.full(n, 1.0 / n)
        centroids.append(data[rng.choice(n, p=probs)])
    centroids = np.array(centroids)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        dists = ((data[:, None, :] - centroids[None, :, :]) ** 2).sum(-1)
        new_labels = dists.argmin(axis=1)
        if (new_labels == labels).all():
            break
        labels = new_labels
        for j in range(k):
            pts = data[labels == j]
            if len(pts):
                centroids[j] = pts.mean(axis=0)
    inertia = float(((data - centroids[labels]) ** 2).sum())
    return centroids, labels, inertia


def choose_k(data: np.ndarray, candidates=K_CANDIDATES, seed: int = SEED) -> int:
    """Elbow pick: smallest k within 15% of the best inertia improvement."""
    if len(data) < 4:
        return 1
    inertias = {}
    for k in candidates:
        if k > len(data):
            break
        _, _, inertia = kmeans(data, k, seed)
        inertias[k] = inertia
    if not inertias:
        return 1
    ks = sorted(inertias)
    best = ks[0]
    for k in ks[1:]:
        gain = (inertias[ks[ks.index(k) - 1]] - inertias[k]) / max(inertias[ks[ks.index(k) - 1]], 1e-9)
        if gain > 0.15:
            best = k
    return best


class OpeningRouteResult(AnalysisResult):
    side: str = "T"
    k: int = 0
    # centroid routes: list of {route: [[x,y] × N_POINTS], rounds: [round numbers], share: float}
    routes: list[dict] = Field(default_factory=list)
    map_bounds: dict = Field(default_factory=dict)
    # Phase I (P3): the CT result ships alongside T instead of being dropped
    ct_k: int = 0
    ct_routes: list[dict] = Field(default_factory=list)


@register_module
class OpeningRouteModule(AnalysisModule):
    name = "routes"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        t_res = self._cluster_side(demo, 2.0, "T")
        ct_res = self._cluster_side(demo, 3.0, "CT")
        # P3: carry both sides on one result (the old ctx.put hack lost the
        # CT data between the module memo and the payload builder)
        t_res.ct_k = ct_res.k
        t_res.ct_routes = ct_res.routes
        return t_res

    def _cluster_side(self, demo: ParsedDemo, side_code: float, side_name: str) -> OpeningRouteResult:
        ticks = demo.ticks
        res = OpeningRouteResult(module=self.name, demo_hash=demo.metadata.demo_hash, side=side_name)
        if ticks is None or ticks.empty:
            return res
        freeze_ends = round_freeze_ends(demo)
        paths: list[tuple[int, np.ndarray]] = []  # (round, resampled path)
        for i, r in enumerate(demo.regular_rounds):
            # B7: opening window starts at freeze-end — from round_start the
            # frozen buy-time walking polluted the clusters
            t0 = freeze_ends.get(r.number, r.start_tick)
            t1 = t0 + int(OPENING_SECONDS * 64)
            sub = ticks[(ticks["tick"] >= t0) & (ticks["tick"] < t1) & (ticks["team_num"] == side_code)]
            if sub.empty:
                continue
            team_paths = []
            for sid, g in sub.groupby("steamid"):
                g = g.sort_values("tick").dropna(subset=["X", "Y"])
                if len(g) < 2:
                    continue
                p = resample_path(g["X"].to_numpy(), g["Y"].to_numpy())
                if p is not None:
                    team_paths.append(p)
            if not team_paths:
                continue
            mean_path = np.mean(team_paths, axis=0)  # (N_POINTS, 2) team-average route
            paths.append((i + 1, mean_path))
        if len(paths) < 3:
            return res  # too few rounds to cluster meaningfully
        data = np.array([p for _, p in paths])  # (rounds, N_POINTS, 2)
        flat = data.reshape(len(paths), -1)
        k = choose_k(flat)
        if k < 2:
            res.k = 1
            res.routes = [{"route": paths[0][1].tolist(), "rounds": [r for r, _ in paths], "share": 1.0}]
            return res
        centroids, labels, _ = kmeans(flat, k)
        for j in range(k):
            members = [r for (r, _), lab in zip(paths, labels) if lab == j]
            res.routes.append({
                "route": centroids[j].reshape(N_POINTS, 2).tolist(),
                "rounds": members,
                "share": round(len(members) / len(paths), 3),
            })
        res.routes.sort(key=lambda x: -x["share"])
        res.k = k
        return res
