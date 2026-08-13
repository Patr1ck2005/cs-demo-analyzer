"""Cross-demo aggregate charts (LTG-2 stage 2) — matplotlib PNGs.

- player_matrix: players x demos rating heatmap
- team_win:      per-demo T/CT win-rate bars
- trends:        per-demo cumulative T/CT score lines
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from cs_analyzer.analysis.aggregate import AggregateResult

_BG = "#0f1419"
_PANEL = "#1a222c"


def _ax_style(ax) -> None:
    ax.set_facecolor(_PANEL)
    for spine in ax.spines.values():
        spine.set_color("#2c3b4d")
    ax.tick_params(colors="#8fa3b8", labelsize=9)
    ax.xaxis.label.set_color("#8fa3b8")
    ax.yaxis.label.set_color("#8fa3b8")


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def render_aggregate_charts(result: AggregateResult, out_dir: Path) -> dict[str, str]:
    from cs_analyzer.render.fonts import setup_fonts

    setup_fonts("Microsoft YaHei")
    out_dir = Path(out_dir)
    paths: dict[str, str] = {}

    # ---- player matrix: players (top 12) x demos, colored by Rating ----
    players = result.players[:12]
    demos = result.demos
    if players and demos:
        ratings = np.zeros((len(players), len(demos)), dtype=float)
        for i, p in enumerate(players):
            for j, d in enumerate(demos):
                match = next((x for x in p.demos if x.get("demo") == d.filename), None)
                ratings[i, j] = match["Rating"] if match else np.nan
        fig, ax = plt.subplots(figsize=(max(6, len(demos) * 1.4 + 3), max(4, len(players) * 0.45 + 2)))
        fig.patch.set_facecolor(_BG)
        masked = np.ma.masked_invalid(ratings)
        im = ax.imshow(masked, cmap="YlOrRd", aspect="auto", vmin=0.4, vmax=1.3)
        ax.set_xticks(range(len(demos)))
        ax.set_xticklabels([d.filename[:12] for d in demos], rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(players)))
        ax.set_yticklabels([f"{p.name} ({p.demo_count}场)" for p in players], fontsize=8)
        for i in range(len(players)):
            for j in range(len(demos)):
                if not np.isnan(ratings[i, j]):
                    ax.text(j, i, f"{ratings[i, j]:.2f}", ha="center", va="center",
                            fontsize=7, color="black")
        ax.set_title("选手跨场 Rating 矩阵", color="white", fontsize=13)
        _ax_style(ax)
        fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
        path = out_dir / "player_matrix.png"
        _save(fig, path)
        paths["player_matrix"] = "player_matrix.png"

    # ---- team win-rate bars per demo ----
    if demos:
        fig, ax = plt.subplots(figsize=(max(6, len(demos) * 0.9), 4.5))
        fig.patch.set_facecolor(_BG)
        names = [d.filename[:14] for d in demos]
        t = [d.t_win_rate * 100 for d in demos]
        ct = [(1 - d.t_win_rate) * 100 for d in demos]
        x = np.arange(len(demos))
        ax.bar(x - 0.2, t, width=0.4, label="T 胜率%", color="#FBBF24", alpha=0.85)
        ax.bar(x + 0.2, ct, width=0.4, label="CT 胜率%", color="#60A5FA", alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("胜率 %")
        ax.legend(fontsize=9)
        ax.set_title("每场 T/CT 胜率", color="white", fontsize=13)
        _ax_style(ax)
        path = out_dir / "team_win.png"
        _save(fig, path)
        paths["team_win"] = "team_win.png"

    # ---- round trends: cumulative T score per demo ----
    if demos:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        fig.patch.set_facecolor(_BG)
        for d in demos:
            rs = [p["round"] for p in d.trend]
            ts = [p["t_score"] for p in d.trend]
            ax.plot(rs, ts, marker="o", markersize=3, linewidth=1.4,
                    label=d.filename[:14])
        ax.set_xlabel("回合")
        ax.set_ylabel("T 累计得分")
        ax.legend(fontsize=8, loc="upper left")
        ax.set_title("各场 T 方得分趋势", color="white", fontsize=13)
        _ax_style(ax)
        path = out_dir / "trends.png"
        _save(fig, path)
        paths["trends"] = "trends.png"

    return paths
