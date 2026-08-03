"""Layer 4: Renderers.

- RadarChartRenderer: migrated from cs_radar_chart.py, config-driven
- ActionMapRenderer: 2D trajectory heatmaps (P1)
- OverlapAnimationRenderer: T/CT trajectory animation (P1)
"""
from cs_analyzer.render.action_map import ActionMapRenderer
from cs_analyzer.render.base import RadarPlayerData, Renderer, merge_for_radar

__all__ = [
    "ActionMapRenderer",
    "RadarPlayerData",
    "Renderer",
    "merge_for_radar",
]
