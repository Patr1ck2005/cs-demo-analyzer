"""Phase N: player style clustering (风格星系, /api/style-map.json).

用户裁决口径（2026-09-05）:
- 特征向量 = 全部 32 个 M5 比率指标（funlab METRIC_DEFS 全键）
- 相似度   = 欧氏距离（稳健标准化空间——中位数/IQR，量纲归一后欧氏才有意义）
- 降维     = PCA 前 2 主成分（numpy SVD，零新依赖）
- 聚类     = Ward 层次聚类（scipy 已装；切簇 = 0.6×最大合并距离，可调）
- 标签     = 簇质心对全局中位数偏离 top3 指标自动拼装（高X/低Y/远Z）
- 门槛     = 复用 funlab_report 的 ≥3 场 gate（M5 口径审计后全指标为比率/每回合，
             天然无"打得多=数值大"偏置）

研究预览定位：n=7（当前库）聚类结果只做参照；样本增长后自动变得有意义，
页面头部注明。零新依赖（不装 sklearn/umap —— HANDOFF 铁律 2b）。
"""
from __future__ import annotations

import threading

import numpy as np

_lock = threading.Lock()
_memo: dict | None = None

#: Ward 切簇阈值 = 阈值系数 × 最大合并距离（小样本经验值；页面注明）
CUT_RATIO = 0.6
#: 星系图不渲染这个数量以下的选手（理论上被 funlab gate 保证，双保险）
MIN_PLAYERS = 2


def style_map_report() -> dict:
    """Memoized style-galaxy report (invalidated with the funlab memo chain)."""
    global _memo
    if _memo is None:
        with _lock:
            if _memo is None:
                _memo = _build()
    return _memo


def invalidate_style_map() -> None:
    global _memo
    with _lock:
        _memo = None


# ---- math steps (module-level pure functions so tests hit them directly) ----


def _feature_matrix(players: list[dict], keys: list[str]) -> tuple[np.ndarray, list[str], list[str]]:
    """(matrix n×k, used_keys, excluded_keys). Excludes all-constant columns
    (no variance → carries no style information)."""
    if not players:
        return np.zeros((0, 0)), [], list(keys)
    raw = np.array([[float(p.get(k, 0.0) or 0.0) for k in keys] for p in players])
    used, excluded, cols = [], [], []
    for j, k in enumerate(keys):
        col = raw[:, j]
        if float(col.max() - col.min()) <= 1e-12:
            excluded.append(k)
            continue
        used.append(k)
        cols.append(col)
    if not cols:
        return np.zeros((len(players), 0)), [], list(keys)
    return np.column_stack(cols), used, excluded


def robust_scale(x: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """(x - median) / IQR per column; IQR=0 falls back to std; still 0 → drop.

    Returns (scaled_matrix, dropped_keys) — the caller passes keys in the same
    order as columns and removes the dropped ones from its label copy.
    """
    med = np.median(x, axis=0)
    q75, q25 = np.percentile(x, [75, 25], axis=0)
    iqr = q75 - q25
    std = x.std(axis=0)
    scale = np.where(iqr > 1e-12, iqr, np.where(std > 1e-12, std, 1.0))
    z = (x - med) / scale
    drop = [j for j in range(x.shape[1])
            if not (iqr[j] > 1e-12) and not (std[j] > 1e-12)]
    keep = [j for j in range(x.shape[1]) if j not in drop]
    return z[:, keep] if keep else np.zeros((x.shape[0], 0)), drop


def pca_2d(z: np.ndarray) -> tuple[np.ndarray, float, float]:
    """First two principal components via SVD; returns (coords, var_pc1, var_pc2)."""
    if z.shape[1] == 0 or z.shape[0] < 2:
        return np.zeros((z.shape[0], 2)), 0.0, 0.0
    zc = z - z.mean(axis=0, keepdims=True)
    u, s, _vt = np.linalg.svd(zc, full_matrices=False)
    coords = u[:, :2] * s[:2]
    var = s**2
    total = float(var.sum()) or 1.0
    v1 = float(var[0] / total) if len(var) else 0.0
    v2 = float(var[1] / total) if len(var) > 1 else 0.0
    return coords, v1, v2


def ward_clusters(z: np.ndarray, cut_ratio: float = CUT_RATIO) -> list[int]:
    """Ward linkage cut at cut_ratio × max merge distance → cluster id per row."""
    from scipy.cluster.hierarchy import fcluster, linkage

    n = z.shape[0]
    if n <= 1 or z.shape[1] == 0:
        return [0] * n
    # 合并距离以稳健 z 空间度量（与相似度口径一致）
    link = linkage(z, method="ward")
    max_d = float(link[-1, 2]) if len(link) else 0.0
    if max_d <= 1e-12:
        return [0] * n
    labels = fcluster(link, t=cut_ratio * max_d, criterion="distance")
    return [int(v) - 1 for v in labels]  # fcluster is 1-based


def cluster_labels(z: np.ndarray, labels: list[int], keys: list[str],
                   key_label: dict[str, str], top: int = 3) -> dict[int, str]:
    """Auto name per cluster: top-|contrast| features of the centroid vs the
    mean of the OTHER centroids (contrastive — every cluster gets a distinct
    name; deviating vs the global median produced 6 identical labels when an
    outlier stretches the median, observed on the real library)."""
    out: dict[int, str] = {}
    cids = sorted(set(labels))
    centroids = {c: z[[i for i, l in enumerate(labels) if l == c]].mean(axis=0)
                 for c in cids}
    for cid in cids:
        others = [centroids[c] for c in cids if c != cid]
        if not others:
            out[cid] = "均衡型"
            continue
        dev = centroids[cid] - np.mean(others, axis=0)
        order = np.argsort(-np.abs(dev))[:top] if len(dev) else []
        parts = []
        for j in order:
            if j >= len(keys):
                continue
            parts.append(("高" if dev[j] >= 0 else "低") + key_label.get(keys[j], keys[j]))
        out[cid] = "·".join(parts) if parts else "均衡型"
    return out


def nearest_neighbors(z: np.ndarray) -> list[tuple[int, int, float]]:
    """[(i, j_nearest, dist)] — euclidean in the same robust-z space, j≠i."""
    out = []
    n = z.shape[0]
    for i in range(n):
        best_j, best_d = -1, float("inf")
        for j in range(n):
            if i == j:
                continue
            d = float(np.linalg.norm(z[i] - z[j]))
            if d < best_d:
                best_j, best_d = j, d
        out.append((i, best_j, round(best_d, 3) if best_j >= 0 else 0.0))
    return out


def personal_style(z_row: np.ndarray, global_med: np.ndarray, keys: list[str],
                   key_label: dict[str, str], top: int = 3) -> str:
    """个人风格画像：自己 vs 全库中位数的 top-|偏离| 特征（高X/低Y）。

    Ward 在小样本上常切出单一巨簇，簇标签同质化；此时个人画像才是
    "你的风格是什么"的有效答案（n=7 实测全员一簇 → 逐人画像兜底）。
    """
    dev = z_row - global_med
    order = np.argsort(-np.abs(dev))[:top] if len(dev) else []
    parts = []
    for j in order:
        if j >= len(keys):
            continue
        parts.append(("高" if dev[j] >= 0 else "低") + key_label.get(keys[j], keys[j]))
    return "·".join(parts) if parts else "均衡型"


# ---- assembly ----


def _build() -> dict:
    from cs_analyzer.web.funlab_data import METRIC_DEFS, funlab_report

    report = funlab_report()
    players = report.get("players", [])
    keys = sorted(METRIC_DEFS.keys())
    label_of = {k: str(v.get("label", k)).split("（")[0] for k, v in METRIC_DEFS.items()}

    if len(players) < MIN_PLAYERS:
        return {
            "note": "样本不足（≥3 场选手少于 2 人），风格星系未生成",
            "n_players": len(players), "points": [], "features_used": [],
            "features_excluded": [], "pca": {"var_pc1": 0.0, "var_pc2": 0.0},
            "cut_ratio": CUT_RATIO, "gate": report.get("gate", {}),
            "trajectories": [],
        }

    x, used, excluded = _feature_matrix(players, keys)
    # keep label/keys aligned with dropped columns from scaling
    z, drop_idx = robust_scale(x)
    used_z = [used[j] for j in range(len(used)) if j not in drop_idx]
    label_z = {k: label_of[k] for k in used_z}
    coords, v1, v2 = pca_2d(z)
    labels = ward_clusters(z)
    names = cluster_labels(z, labels, used_z, label_z)
    nn = nearest_neighbors(z)
    global_med = np.median(z, axis=0) if len(z) else np.zeros(0)
    one_cluster = len(set(labels)) <= 1

    palette = ["#a78bfa", "#3ddc97", "#ffb02e", "#3d9bff", "#ff4d5e", "#f472b6"]
    points = []
    for i, p in enumerate(players):
        cid = labels[i]
        j, dist = (nn[i][1], nn[i][2]) if nn[i][1] >= 0 else (-1, 0.0)
        # 单一巨簇时标签退化为个人画像（否则 7 人同名标签无区分度）
        style = (personal_style(z[i], global_med, used_z, label_z)
                 if one_cluster else names.get(cid, "均衡型"))
        points.append({
            "steamid": p.get("steamid", ""), "name": p.get("name", ""),
            "demos": p.get("demos", 0), "kills": p.get("kills", 0),
            "x": round(float(coords[i, 0]), 4), "y": round(float(coords[i, 1]), 4),
            "cluster": cid, "label": style,
            "color": palette[cid % len(palette)],
            "nearest": ({"name": players[j].get("name", ""), "dist": dist}
                        if j >= 0 else None),
        })

    trajectories = _style_trajectories(players, keys, used_z, label_z)

    return {
        "note": "研究预览：全 32 指标 · 稳健标准化 · 欧氏距离 · Ward 聚类；样本增长后星系自动变有意义",
        "n_players": len(players),
        "features_used": used_z, "features_excluded": excluded,
        "pca": {"var_pc1": round(v1, 3), "var_pc2": round(v2, 3)},
        "cut_ratio": CUT_RATIO, "gate": report.get("gate", {}),
        "points": points,
        "trajectories": trajectories,
    }


def _style_trajectories(players: list[dict], keys: list[str], used_z: list[str],
                         label_z: dict[str, str]) -> list[dict]:
    """V3 风格演变：同一选手按时间窗（每 ~5 场一窗）向量漂移轨迹。

    Uses the funlab scan's per-demo entries: for each player with demos
    spanning multiple dates, split chronologically into windows, compute the
    metric vector per window, project through the SAME robust scaler + PCA
    fitted on the full player matrix, and emit polyline points (oldest→newest)
    plus a change note when the biggest per-window jump exceeds 1.5 z-units.
    """
    from cs_analyzer.web.funlab_data import _scan_all

    scan = _scan_all()
    if not scan or not scan.get("entries"):
        return []
    # index: sid -> [(date, demo_hash)] and per-demo player vectors
    from collections import defaultdict

    per_demo_vectors: dict[str, dict[str, dict]] = {}  # demo_hash -> sid -> metrics
    for e in scan["entries"]:
        per_demo_vectors[e["demo_hash"]] = {p["steamid"]: p for p in e["players"]}

    # reuse the fitted scaler: rebuild z from the same rows to get (mu, sd)
    raw = np.array([[float(p.get(k, 0.0) or 0.0) for k in keys] for p in players])
    mu = np.median(raw, axis=0)
    q75, q25 = np.percentile(raw, [75, 25], axis=0)
    iqr = q75 - q25
    std = raw.std(axis=0)
    scale = np.where(iqr > 1e-12, iqr, np.where(std > 1e-12, std, 1.0))
    # project helper: vector -> PC coords via the SAME SVD basis
    zfull = (raw - mu) / scale
    zc = zfull - zfull.mean(axis=0, keepdims=True)
    _u, s, vt = np.linalg.svd(zc, full_matrices=False)

    # player -> [(date, demo_hash)] sorted by date
    roster = {p["steamid"]: p for p in players}
    history: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in scan["entries"]:
        date = e.get("date")
        if not date:
            continue
        for sid in e["player_ids"]:
            if sid in roster:
                history[sid].append((date, e["demo_hash"]))
    # also carry WMPVP demos (no date) at the end in file order
    for e in scan["entries"]:
        if e.get("date"):
            continue
        for sid in e["player_ids"]:
            if sid in roster:
                history[sid].append(("9999", e["demo_hash"]))

    WINDOW = 5
    out = []
    for sid, entries in history.items():
        if sid not in roster:
            continue
        entries = sorted(set(entries))
        if len(entries) < 2:
            continue  # no evolution without ≥2 windows
        windows = [entries[i:i + WINDOW] for i in range(0, len(entries), WINDOW)]
        if len(windows) < 2:
            continue
        pts = []
        prev_z = None
        max_jump = 0.0
        for wi, win in enumerate(windows):
            vecs = []
            for _date, dh in win:
                p = per_demo_vectors.get(dh, {}).get(sid)
                if p:
                    vecs.append([float(p.get(k, 0.0) or 0.0) for k in keys])
            if not vecs:
                continue
            zv = (np.mean(np.array(vecs), axis=0) - mu) / scale
            zr_ = (zv - zfull.mean(axis=0, keepdims=True)[0]) @ vt[:2].T
            pts.append({"window": wi + 1, "n_demos": len(win),
                        "x": round(float(zr_[0]), 4), "y": round(float(zr_[1]), 4)})
            if prev_z is not None:
                max_jump = max(max_jump, float(np.linalg.norm(zv - prev_z)))
            prev_z = zv
        if len(pts) < 2:
            continue
        # change threshold scales with dimensionality: 1.5σ per dim in a
        # k-dim z space = 1.5·√k euclidean (8.1 at k=29)
        changed = max_jump > 1.5 * (len(used_z) ** 0.5)
        out.append({
            "steamid": sid, "name": roster[sid].get("name", sid),
            "points": pts, "max_jump": round(max_jump, 2),
            # X4c: client-side drift threshold needs k (z-dimension count) to
            # evaluate max_jump > σ·√k with the user's σ; server change_note
            # stays computed at the default 1.5σ for non-JS consumers.
            "n_features": len(used_z),
            "change_note": ("风格明显漂移" if changed else "风格稳定"),
        })
    return out


# ---- T1 snapshot pair (called by web.snapshots under _lock) ----

def _snapshot_payload() -> dict | None:
    return _memo


def restore_snapshot(payload: dict) -> None:
    global _memo
    _memo = payload
