"""Preference visualization charts (matplotlib PNGs for the web platform).

- heatmap:   sampled position density (hexbin) over the map
- utility:   smoke/flash/he/molly detonation positions per type
- style:     peek aggressiveness + crosshair placement mini-panel
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from cs_analyzer.analysis.preference import PlayerPreference
from cs_analyzer.maps import MapResource

_BG = "#0f1419"
_PANEL = "#1a222c"
_UTIL_COLORS = {"smoke": "#9E9E9E", "flash": "#FFFFFF", "he": "#FF8800", "molly": "#FF6600"}


def _dark_axes(ax) -> None:
    ax.set_facecolor(_PANEL)
    for spine in ax.spines.values():
        spine.set_color("#2c3b4d")
    ax.tick_params(colors="#8fa3b8", labelsize=8)
    ax.xaxis.label.set_color("#8fa3b8")
    ax.yaxis.label.set_color("#8fa3b8")


def _world_to_px(pref: PlayerPreference, map_res: MapResource, pts):
    px, py = map_res.world_to_pixel_array([p[0] for p in pts], [p[1] for p in pts])
    return np.asarray(px, dtype=float), np.asarray(py, dtype=float)


def _fonts():
    from cs_analyzer.render.fonts import setup_fonts

    setup_fonts("Microsoft YaHei")


def render_heatmap(pref: PlayerPreference, map_res: MapResource, out_path: str | Path) -> Path:
    _fonts()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    fig.patch.set_facecolor(_BG)
    _dark_axes(ax)
    samples = pref.position_samples
    if samples:
        px, py = _world_to_px(pref, map_res, samples)
        ax.hexbin(px, py, gridsize=28, cmap="YlOrRd", mincnt=1, alpha=0.85)
    ax.set_xlim(0, map_res.image_width)
    ax.set_ylim(0, map_res.image_height)
    ax.invert_yaxis()
    ax.set_title(f"{pref.name} 位置热力图", color="white", fontsize=13)
    ax.set_xlabel("X (px)")
    ax.set_ylabel("Y (px)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


def render_utility_map(pref: PlayerPreference, map_res: MapResource, out_path: str | Path) -> Path:
    _fonts()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    fig.patch.set_facecolor(_BG)
    _dark_axes(ax)
    for kind, pts in pref.utility_positions.items():
        if not pts:
            continue
        px, py = _world_to_px(pref, map_res, pts)
        ax.scatter(px, py, s=42, color=_UTIL_COLORS.get(kind, "#FFFFFF"),
                   edgecolors="black", linewidths=0.4, alpha=0.85, label=kind)
    ax.set_xlim(0, map_res.image_width)
    ax.set_ylim(0, map_res.image_height)
    ax.invert_yaxis()
    ax.set_title(f"{pref.name} 道具落点", color="white", fontsize=13)
    if any(pref.utility_positions.values()):
        ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


def render_style_panel(pref: PlayerPreference, out_path: str | Path) -> Path:
    _fonts()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.0))
    fig.patch.set_facecolor(_BG)
    for ax in axes:
        _dark_axes(ax)

    # peek aggressiveness: 0 = very aggressive (early), 1 = passive
    ax = axes[0]
    frac = pref.avg_first_engagement_fraction
    ax.barh([0], [frac], color="#29B6F6", alpha=0.85, height=0.6)
    ax.barh([0], [1 - frac], left=[frac], color="#0288D1", alpha=0.5, height=0.6)
    ax.set_yticks([])
    ax.set_xlim(0, 1)
    label = "很激进" if frac < 0.4 else ("均衡" if frac < 0.6 else "很被动")
    ax.set_title(f"首交战时机 {label} ({frac:.2f})", color="white", fontsize=11)

    # crosshair placement: avg pitch degrees
    ax = axes[1]
    pitch = pref.avg_pitch
    ax.barh([0], [pitch], color="#FFD54F", alpha=0.85, height=0.6)
    ax.axvline(0, color="white", lw=0.8)
    ax.set_yticks([])
    ax.set_title(f"平均准星仰角 {pitch:.1f}°", color="white", fontsize=11)

    fig.suptitle(f"{pref.name} 风格特征", color="white", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path
