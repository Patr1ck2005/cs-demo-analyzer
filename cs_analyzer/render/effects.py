"""Visual effects for the 2D replay renderer.

Manages pooled matplotlib artists (never created/destroyed per frame). Each
effect kind has sorted (start_tick, end_tick, px, py) arrays; per frame we find
the active set via np.searchsorted and update pool artists in place.
"""
from __future__ import annotations

import numpy as np
from matplotlib.patches import Circle

from cs_analyzer.config import ReplayConfig
from cs_analyzer.maps.loader import MapResource
from cs_analyzer.replay.timeline import PlayerTimeline

_SIDE_T = "#FF6B6B"
_SIDE_CT = "#4ECDC4"


class EffectManager:
    """Owns all effect layers and updates their artists each frame."""

    def __init__(
        self, config: ReplayConfig, timeline: PlayerTimeline, map_resource: MapResource, tick_rate: int = 64
    ) -> None:
        self.config = config
        self._tick_rate = tick_rate
        self._map = map_resource
        self._to_px = map_resource.world_to_pixel_array

        # Build per-kind data from the timeline.
        self._smoke = self._area_arrays(timeline.utilities.get("smoke", []), config.smoke_duration)
        self._flash = self._area_arrays(timeline.utilities.get("flash", []), config.flash_duration)
        self._he = self._area_arrays(timeline.utilities.get("he", []), config.he_duration)
        self._fire = self._area_arrays(timeline.utilities.get("fire", []), config.molotov_duration)

        self._shots = self._marker_arrays([(e.tick, e.x, e.y) for e in timeline.shots], 0)
        self._kills = self._kill_arrays(timeline.kills, config.kill_duration)
        self._deaths = self._marker_arrays([(e.tick, e.x, e.y) for e in timeline.deaths], config.death_duration)
        self._jumps = self._marker_arrays([(e.tick, e.x, e.y) for e in timeline.jumps], config.jump_duration)

        # Artist pools (created in attach() once the axis exists).
        self.smoke_circles: list = []
        self.flash_circles: list = []
        self.he_circles: list = []
        self.fire_circles: list = []
        self.shot_marks: list = []
        self.jump_marks: list = []
        self.death_marks: list = []
        self.kill_marks: list = []
        self.victim_marks: list = []
        self.kill_lines: list = []
        self._attached = False

    # ---- data building ----

    def _seconds_to_ticks(self, seconds: float) -> int:
        return int(round(seconds * self._tick_rate))

    def _area_arrays(self, events, duration_seconds: float) -> dict:
        if not events:
            return {"starts": np.array([]), "ends": np.array([]), "px": np.array([]), "py": np.array([])}
        dur = self._seconds_to_ticks(duration_seconds)
        starts = np.array([e.tick for e in events], dtype=float)
        px, py = self._convert([(e.x, e.y) for e in events])
        return {"starts": starts, "ends": starts + dur, "px": px, "py": py}

    def _marker_arrays(self, events, duration_seconds: float) -> dict:
        if not events:
            return {"starts": np.array([]), "ends": np.array([]), "px": np.array([]), "py": np.array([])}
        dur = self._seconds_to_ticks(duration_seconds)
        starts = np.array([t for t, _, _ in events], dtype=float)
        px, py = self._convert([(x, y) for _, x, y in events])
        return {"starts": starts, "ends": starts + dur, "px": px, "py": py}

    def _kill_arrays(self, kills, duration_seconds: float) -> dict:
        if not kills:
            return {
                "starts": np.array([]), "ends": np.array([]),
                "px": np.array([]), "py": np.array([]),
                "vpx": np.array([]), "vpy": np.array([]),
            }
        dur = self._seconds_to_ticks(duration_seconds)
        starts = np.array([k.tick for k in kills], dtype=float)
        px, py = self._convert([(k.x, k.y) for k in kills])
        vpx, vpy = self._convert([(k.victim_x, k.victim_y) for k in kills])
        return {
            "starts": starts, "ends": starts + dur, "px": px, "py": py,
            "vpx": vpx, "vpy": vpy,
        }

    def _convert(self, pts):
        px, py = self._to_px([p[0] for p in pts], [p[1] for p in pts])
        return np.asarray(px, dtype=float), np.asarray(py, dtype=float)

    # ---- artist pools ----

    def _make_circle_pool(self, n: int, fill: bool = True):
        return [Circle((0, 0), 0, alpha=0, fill=fill) for _ in range(n)]

    def _make_marker_pool(self, ax, n: int, marker: str, color: str, size: float, zorder: int = 7):
        """Pool of Line2D markers (matplotlib markers, not font glyphs)."""
        pool = []
        for _ in range(n):
            (line,) = ax.plot([], [], marker=marker, color=color, markersize=size,
                              markeredgecolor="black", markeredgewidth=0.5,
                              linestyle="None", alpha=0, zorder=zorder)
            pool.append(line)
        return pool

    # ---- per-frame update ----

    def attach(self, ax) -> None:
        """Create pools (needs the axis) and add all artists to it once."""
        self.smoke_circles = self._make_circle_pool(6)
        self.flash_circles = self._make_circle_pool(4)
        self.he_circles = self._make_circle_pool(4, fill=False)
        self.fire_circles = self._make_circle_pool(6)
        self.shot_marks = self._make_marker_pool(ax, 8, "o", "#FFD700", 5)
        self.jump_marks = self._make_marker_pool(ax, 6, "^", "#FFFFFF", 8)
        self.death_marks = self._make_marker_pool(ax, 6, "X", "#FF3333", 9)
        self.kill_marks = self._make_marker_pool(ax, 6, "*", "#FFD700", 15, zorder=8)
        self.victim_marks = self._make_marker_pool(ax, 6, "X", "#FF6666", 7)
        self.kill_lines = []
        for _ in range(6):
            line, = ax.plot([], [], color="#FFD700", linewidth=1.5, alpha=0, zorder=6)
            self.kill_lines.append(line)
        self._attached = True

    def update(self, tick: float) -> None:
        """Update all effect artists for a game tick. ax must already hold them."""
        self._update_circles(self.smoke_circles, self._smoke, tick, radius=90, alpha=0.35, color="#AAAAAA")
        self._update_circles(self.fire_circles, self._fire, tick, radius=45, alpha=0.5, color="#FF6600")
        self._update_circles(self.flash_circles, self._flash, tick, radius=120, alpha=0.9, color="#FFFFFF")
        self._update_circles(self.he_circles, self._he, tick, radius=70, alpha=0.9, color="#FF3333", fill=False)
        self._update_marks(self.shot_marks, self._shots, tick)
        self._update_marks(self.jump_marks, self._jumps, tick)
        self._update_marks(self.death_marks, self._deaths, tick)
        self._update_kills(tick)

    def _active_idx(self, data: dict, tick: float) -> np.ndarray:
        starts, ends = data["starts"], data["ends"]
        if starts.size == 0:
            return np.array([], dtype=int)
        lo = np.searchsorted(starts, tick, side="right")
        active = np.nonzero(ends[:lo] >= tick)[0]
        return active

    def _update_circles(self, pool, data, tick, radius, alpha, color, fill=True) -> None:
        active = self._active_idx(data, tick)
        shown = min(len(active), len(pool))
        # hide all first
        for c in pool:
            c.set_visible(False)
        for j in range(shown):
            i = active[j]
            c = pool[j]
            age = tick - data["starts"][i]
            dur = max(data["ends"][i] - data["starts"][i], 1)
            prog = min(age / dur, 1.0)
            r = radius * (0.4 + 0.6 * prog)
            a = alpha * (1.0 - prog * 0.8)
            c.set_center((data["px"][i], data["py"][i]))
            c.set_radius(r)
            c.set_alpha(max(a, 0.0))
            if fill:
                c.set_color(color)
            else:
                c.set_edgecolor(color)
                c.set_linewidth(2.5)
                c.set_facecolor("none")
            c.set_visible(True)

    def _update_marks(self, pool, data, tick) -> None:
        active = self._active_idx(data, tick)
        shown = min(len(active), len(pool))
        for m in pool:
            m.set_alpha(0)
        for j in range(shown):
            i = active[j]
            m = pool[j]
            m.set_data([data["px"][i]], [data["py"][i]])
            age = tick - data["starts"][i]
            dur = max(data["ends"][i] - data["starts"][i], 1)
            prog = min(age / dur, 1.0)
            m.set_alpha(1.0 - prog * 0.7)
            m.set_visible(True)

    def _update_kills(self, tick) -> None:
        data = self._kills
        active = self._active_idx(data, tick)
        shown = min(len(active), len(self.kill_marks))
        for m in self.kill_marks + self.victim_marks:
            m.set_alpha(0)
        for line in self.kill_lines:
            line.set_alpha(0)
        for j in range(shown):
            i = active[j]
            km = self.kill_marks[j]
            vm = self.victim_marks[j]
            line = self.kill_lines[j]
            km.set_data([data["px"][i]], [data["py"][i]])
            vm.set_data([data["vpx"][i]], [data["vpy"][i]])
            line.set_data([data["px"][i], data["vpx"][i]], [data["py"][i], data["vpy"][i]])
            age = tick - data["starts"][i]
            dur = max(data["ends"][i] - data["starts"][i], 1)
            prog = min(age / dur, 1.0)
            alpha = 1.0 - prog * 0.7
            km.set_alpha(alpha)
            vm.set_alpha(alpha)
            line.set_alpha(alpha)
