"""Static hexagonal radar chart renderer (matplotlib, ~1s per player).

The web platform (LTG-2) uses this instead of the slow Manim video render so
player-detail pages can draw a radar chart per player instantly.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from cs_analyzer.config import RadarChartConfig
from cs_analyzer.render.base import RadarPlayerData

_BG = "#0f1419"
_PANEL = "#1a222c"
_GRID = "#2c3b4d"
_TOP = "#FFD700"
_NORMAL = "#FFFFFF"


def _angles(n: int) -> np.ndarray:
    return np.linspace(0, 2 * np.pi, n, endpoint=False) + np.pi / 2


def _fmt(attr: str, value: float) -> str:
    if attr in ("Headshot%", "KAST%") or attr.endswith("%"):
        return f"{value:.0f}%"
    return f"{value:.2f}"


def render_radar_static(
    player: RadarPlayerData,
    config: RadarChartConfig,
    out_path,
    size: int = 480,
    dpi: int = 100,
):
    """Draw one player's radar chart to a PNG."""
    from pathlib import Path

    from cs_analyzer.render.fonts import setup_fonts

    setup_fonts("Microsoft YaHei")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    attrs = list(config.attributes)
    n = len(attrs)
    angles = _angles(n)

    fig, ax = plt.subplots(
        figsize=(size / dpi, size / dpi),
        dpi=dpi,
        subplot_kw=dict(polar=True),
    )
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_PANEL)
    ax.grid(False)

    # concentric rings + spokes
    for ring in (1, 2, 3, 4, 5, 6):
        ax.plot(angles, [ring / 6.0] * n, color=_GRID, lw=0.9, zorder=1)
    for a in angles:
        ax.plot([a, a], [0, 1], color=_GRID, lw=0.9, zorder=1)

    ax.set_xticks(angles)
    ax.set_xticklabels(attrs, fontsize=9, color="white", zorder=5)
    ax.set_ylim(0, 1)
    ax.set_yticks([])

    # normalized values
    vals = []
    for attr in attrs:
        raw = player.attribute_value(attr)
        lo, hi = config.attribute_ranges.get(attr, (0.0, 1.0))
        norm = (raw - lo) / (hi - lo) if hi > lo else 0.0
        vals.append(max(min(norm, 1.0), 0.0))

    color = _TOP if player.is_top else _NORMAL
    ring_pts = [(angles[i], vals[i]) for i in range(n)]
    closed = ring_pts + [ring_pts[0]]
    ax.plot([p[0] for p in closed], [p[1] for p in closed], color=color, lw=2.2, zorder=3)
    ax.fill([p[0] for p in closed], [p[1] for p in closed], color=color, alpha=0.16, zorder=2)

    # value labels (gold when rank #1)
    for i, attr in enumerate(attrs):
        rank = player.attribute_rank(attr)
        label_color = _TOP if rank == 1 else "#8fa3b8"
        ax.text(
            angles[i], vals[i] + 0.14, _fmt(attr, player.attribute_value(attr)),
            ha="center", va="center", fontsize=9, color=label_color, zorder=6,
        )

    # title: player name + team + top badge
    top_suffix = " ★ TOP" if player.is_top else ""
    fig.suptitle(
        f"{player.ID}  {player.team}{top_suffix}",
        color="white", fontsize=13, y=0.96,
    )
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path
