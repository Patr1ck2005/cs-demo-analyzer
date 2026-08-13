"""Visual effects for the 2D replay renderer (pro-minimap style).

Owns pooled matplotlib artists (never created/destroyed per frame). Each
effect kind has sorted (start_tick, end_tick, px, py) arrays; per frame we find
the active set via np.searchsorted and update pool artists in place.

Effect layers:
- projectiles  : animated grenade flight (throw origin -> landing point)
- smoke        : growing smoke cloud that persists its real in-game lifetime
- flash        : brief white burst
- he           : explosion ring
- fire         : persistent fire zone (inferno lifetime)
- shots/jumps  : action markers (jump also gets an expanding ring)
- kills/deaths : kill connection lines + victim/dying markers
"""
from __future__ import annotations

import numpy as np
from matplotlib.patches import Circle

from cs_analyzer.config import ReplayConfig
from cs_analyzer.maps.loader import MapResource
from cs_analyzer.replay.timeline import PlayerTimeline, TICK_RATE

_SIDE_T = "#FF6B6B"
_SIDE_CT = "#4ECDC4"

_EMPTY = {"starts": np.array([]), "ends": np.array([]), "durs": np.array([]),
          "px": np.array([]), "py": np.array([])}
_EMPTY_KILLS = {"starts": np.array([]), "ends": np.array([]),
                "px": np.array([]), "py": np.array([]),
                "vpx": np.array([]), "vpy": np.array([])}
_EMPTY_PROJ = {"starts": np.array([]), "ends": np.array([]),
               "tpx": np.array([]), "tpy": np.array([]),
               "lpx": np.array([]), "lpy": np.array([]), "color": []}

_N_SMOKE_LAYERS = 5  # offset gray circles per smoke cloud -> irregular volume
_N_FIRE_FLAMES = 8  # flickering flame points per molotov zone
_SMOKE_LAYER_RADII = np.array([1.0, 0.85, 0.7, 0.95, 0.75])
_SMOKE_LAYER_ALPHAS = np.array([0.30, 0.26, 0.22, 0.24, 0.18])


class EffectManager:
    """Owns all effect layers and updates their artists each frame."""

    def __init__(
        self, config: ReplayConfig, timeline: PlayerTimeline, map_resource: MapResource, tick_rate: int = 64
    ) -> None:
        self.config = config
        self._tick_rate = tick_rate
        self._map = map_resource
        self._to_px = map_resource.world_to_pixel_array
        self._alpha_scale = 1.0  # global effect-opacity multiplier (round/end fades)

        # Build per-kind data from the timeline (respecting show_* toggles).
        self._smoke = self._area_arrays(timeline.utilities.get("smoke", []), config.smoke_duration) if config.show_smoke else _EMPTY
        self._flash = self._area_arrays(timeline.utilities.get("flash", []), config.flash_duration) if config.show_flash else _EMPTY
        self._he = self._area_arrays(timeline.utilities.get("he", []), config.he_duration) if config.show_he else _EMPTY
        self._fire = self._area_arrays(timeline.utilities.get("fire", []), config.molotov_duration) if config.show_fire else _EMPTY
        self._molly = self._area_arrays(timeline.utilities.get("molly", []), config.molotov_duration) if config.show_molly else _EMPTY
        self._projectiles = self._projectile_arrays(timeline.utilities) if config.show_projectiles else _EMPTY_PROJ

        self._shots = self._marker_arrays([(e.tick, e.x, e.y) for e in timeline.shots], 0) if config.show_shots else _EMPTY
        self._kills = self._kill_arrays(timeline.kills, config.kill_duration) if config.show_kills else _EMPTY_KILLS
        self._deaths = self._marker_arrays([(e.tick, e.x, e.y) for e in timeline.deaths], config.death_duration) if config.show_deaths else _EMPTY
        self._jumps = self._marker_arrays([(e.tick, e.x, e.y) for e in timeline.jumps], config.jump_duration) if config.show_jumps else _EMPTY

        # Deterministic per-event layer geometry for smoke clouds / flame clusters.
        self._smoke_offsets = self._layer_offsets(self._smoke["px"].size, _N_SMOKE_LAYERS, 0.45)
        self._fire_offsets = self._layer_offsets(self._fire["px"].size, _N_FIRE_FLAMES, 0.65)
        self._fire_phases = self._layer_phases(self._fire["px"].size, _N_FIRE_FLAMES)

        # Artist pools (created in attach() once the axis exists).
        self.smoke_circles: list = []
        self.flash_circles: list = []
        self.he_circles: list = []
        self.fire_circles: list = []
        self.molly_circles: list = []
        self.projectile_lines: list = []
        self.projectile_dots: list = []
        self.shot_marks: list = []
        self.fire_flame_marks: list = []
        self.jump_rings: list = []
        self.death_marks: list = []
        self.kill_marks: list = []
        self.victim_marks: list = []
        self.kill_lines: list = []
        self._attached = False

    # ---- global alpha scaling (V1: fade effects together with the paths) ----

    def set_alpha_scale(self, scale: float) -> None:
        """Global multiplier for every effect artist's alpha (round/end fades)."""
        self._alpha_scale = float(np.clip(scale, 0.0, 1.0))

    def _scaled(self, alpha: float) -> float:
        return float(np.clip(alpha * self._alpha_scale, 0.0, 1.0))

    def _layer_offsets(self, n_events: int, n_layers: int, spread: float) -> np.ndarray:
        """Deterministic per-event layer offsets, fractions of the base radius."""
        if n_events == 0:
            return np.zeros((0, n_layers, 2))
        rng = np.random.RandomState(7)
        offsets = (rng.rand(n_events, n_layers, 2) * 2 - 1) * spread
        offsets[:, 0, :] = 0.0  # layer 0 sits on the center
        return offsets

    def _layer_phases(self, n_events: int, n_layers: int) -> np.ndarray:
        if n_events == 0:
            return np.zeros((0, n_layers))
        return np.random.RandomState(11).rand(n_events, n_layers) * 2 * np.pi

    # ---- data building ----

    def _seconds_to_ticks(self, seconds: float) -> int:
        return int(round(seconds * self._tick_rate))

    def _area_arrays(self, events, default_seconds: float) -> dict:
        if not events:
            return {"starts": np.array([]), "ends": np.array([]), "durs": np.array([]),
                    "px": np.array([]), "py": np.array([])}
        default = self._seconds_to_ticks(default_seconds)
        starts = np.array([e.tick for e in events], dtype=float)
        durs = np.array([getattr(e, "duration_ticks", 0) or default for e in events], dtype=float)
        px, py = self._convert([(e.x, e.y) for e in events])
        return {"starts": starts, "ends": starts + durs, "durs": durs, "px": px, "py": py}

    def _projectile_arrays(self, utilities: dict[str, list]) -> dict:
        """Animated flight windows: throw origin -> landing point."""
        rows = []
        for kind, evs in utilities.items():
            for e in evs:
                if getattr(e, "throw_tick", -1) < 0:
                    continue
                if e.tick <= e.throw_tick:
                    continue
                dx, dy = e.throw_x - e.x, e.throw_y - e.y
                if abs(dx) + abs(dy) < 5.0:
                    continue  # degenerate (throw == landing): just show impact
                rows.append((e.throw_tick, e.tick, e.throw_x, e.throw_y, e.x, e.y, kind))
        if not rows:
            return {"starts": np.array([]), "ends": np.array([]),
                    "tpx": np.array([]), "tpy": np.array([]),
                    "lpx": np.array([]), "lpy": np.array([]), "color": []}
        rows.sort(key=lambda r: r[0])
        starts = np.array([r[0] for r in rows], dtype=float)
        ends = np.array([r[1] for r in rows], dtype=float)
        tpx, tpy = self._convert([(r[2], r[3]) for r in rows])
        lpx, lpy = self._convert([(r[4], r[5]) for r in rows])
        colors = [self.config.projectile_colors.get(r[6], "#FFFFFF") for r in rows]
        return {"starts": starts, "ends": ends, "tpx": tpx, "tpy": tpy,
                "lpx": lpx, "lpy": lpy, "color": colors}

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

    def _add_circles(self, ax, pool) -> None:
        for c in pool:
            ax.add_patch(c)  # Circle() alone does NOT add itself to the axes

    def attach(self, ax) -> None:
        """Create pools (needs the axis) and add all artists to it once."""
        self.smoke_circles = self._make_circle_pool(8 * _N_SMOKE_LAYERS)
        self.flash_circles = self._make_circle_pool(5)
        self.he_circles = self._make_circle_pool(5, fill=False)
        self.fire_circles = self._make_circle_pool(8)
        self.molly_circles = self._make_circle_pool(4, fill=False)
        self._add_circles(ax, self.smoke_circles)
        self._add_circles(ax, self.flash_circles)
        self._add_circles(ax, self.he_circles)
        self._add_circles(ax, self.fire_circles)
        self._add_circles(ax, self.molly_circles)

        self.projectile_lines = []
        self.projectile_dots = []
        for _ in range(14):
            line, = ax.plot([], [], color="#FFFFFF", linewidth=2.0, alpha=0, zorder=6)
            self.projectile_lines.append(line)
            (dot,) = ax.plot([], [], marker="o", color="#FFFFFF", markersize=5,
                             markeredgecolor="black", markeredgewidth=0.5,
                             linestyle="None", alpha=0, zorder=7)
            self.projectile_dots.append(dot)

        # Shots sit BELOW the trail (trail zorder 4) so firing flashes never
        # occlude the player's path. Jump/kill markers stay above for legibility.
        self.shot_marks = self._make_marker_pool(ax, 8, "o", self.config.shot_color, 5, zorder=3)
        self.jump_rings = self._make_circle_pool(6, fill=False)
        for c in self.jump_rings:
            c.set_edgecolor(self.config.jump_color)
            c.set_linewidth(2.2)
        self._add_circles(ax, self.jump_rings)
        self.death_marks = self._make_marker_pool(ax, 6, "$☠$", self.config.death_color, 15)
        self.kill_marks = self._make_marker_pool(ax, 6, "*", self.config.kill_color, 15, zorder=8)
        self.victim_marks = self._make_marker_pool(ax, 6, "X", self.config.victim_color, 7)
        self.kill_lines = []
        for _ in range(6):
            line, = ax.plot([], [], color=self.config.kill_line_color, linewidth=1.5, alpha=0, zorder=6)
            self.kill_lines.append(line)
        self.fire_flame_marks = []
        for _ in range(8 * _N_FIRE_FLAMES):
            (m,) = ax.plot([], [], marker="o", color=self.config.fire_color,
                           markersize=7, linestyle="None", alpha=0, zorder=6)
            self.fire_flame_marks.append(m)
        self._attached = True

    # ---- per-frame update ----

    def update(self, tick: float) -> None:
        """Update all effect artists for a game tick. ax must already hold them."""
        self._update_projectiles(tick)
        self._update_smoke(tick)
        self._update_flash(tick)
        self._update_he(tick)
        self._update_fire(tick)
        self._update_marks(self.shot_marks, self._shots, tick)
        self._update_jump_rings(tick)
        self._update_marks(self.death_marks, self._deaths, tick)
        self._update_kills(tick)

    def _active_idx(self, data: dict, tick: float) -> np.ndarray:
        starts, ends = data["starts"], data["ends"]
        if starts.size == 0:
            return np.array([], dtype=int)
        lo = np.searchsorted(starts, tick, side="right")
        active = np.nonzero(ends[:lo] >= tick)[0]
        return active

    def _projectile_active(self, data: dict, tick: float) -> np.ndarray:
        """Active projectiles: flight window [start, end) — end exclusive,
        because at the landing tick the nade has arrived (area effect takes over)."""
        starts, ends = data["starts"], data["ends"]
        if starts.size == 0:
            return np.array([], dtype=int)
        return np.nonzero((starts <= tick) & (tick < ends))[0]

    def _update_projectiles(self, tick: float) -> None:
        data = self._projectiles
        for line in self.projectile_lines:
            line.set_alpha(0)
        for dot in self.projectile_dots:
            dot.set_alpha(0)
        active = self._projectile_active(data, tick)
        n = min(len(active), len(self.projectile_lines))
        for j in range(n):
            i = active[j]
            dur = max(data["ends"][i] - data["starts"][i], 1.0)
            prog = min(max((tick - data["starts"][i]) / dur, 0.0), 1.0)
            cx = data["tpx"][i] + (data["lpx"][i] - data["tpx"][i]) * prog
            cy = data["tpy"][i] + (data["lpy"][i] - data["tpy"][i]) * prog
            color = data["color"][i] if i < len(data["color"]) else "#FFFFFF"
            line = self.projectile_lines[j]
            dot = self.projectile_dots[j]
            line.set_data([data["tpx"][i], cx], [data["tpy"][i], cy])
            line.set_color(color)
            line.set_alpha(self._scaled(self.config.nade_path_alpha))
            dot.set_data([cx], [cy])
            dot.set_color(color)
            dot.set_markersize(self.config.nade_projectile_size)
            dot.set_alpha(self._scaled(1.0))
        # hide any extras
        for line in self.projectile_lines[n:]:
            line.set_alpha(0)
        for dot in self.projectile_dots[n:]:
            dot.set_alpha(0)

    def _update_smoke(self, tick: float) -> None:
        data = self._smoke
        active = self._active_idx(data, tick)
        n_layers = _N_SMOKE_LAYERS
        shown = min(len(active), len(self.smoke_circles) // n_layers)
        grow = self._seconds_to_ticks(self.config.smoke_grow_seconds)
        fade = self._seconds_to_ticks(self.config.smoke_fade_seconds)
        max_r = self.config.smoke_max_radius
        for c in self.smoke_circles:
            c.set_visible(False)
        for j in range(shown):
            i = active[j]
            age = tick - data["starts"][i]
            dur = max(data["durs"][i], 1)
            if age < grow:
                base_r = max_r * max(age / grow, 0.01)
                base_a = 0.40 * age / grow
            else:
                base_r = max_r
                remain = dur - age
                if remain < fade:
                    base_a = 0.40 * max(remain / fade, 0.0)
                else:
                    base_a = 0.40
            cx, cy = data["px"][i], data["py"][i]
            for L in range(n_layers):
                c = self.smoke_circles[j * n_layers + L]
                ox, oy = self._smoke_offsets[i, L]
                rr = base_r * _SMOKE_LAYER_RADII[L]
                c.set_center((cx + ox * rr, cy + oy * rr))
                c.set_radius(rr)
                c.set_facecolor(self.config.smoke_color)
                c.set_alpha(self._scaled(base_a * _SMOKE_LAYER_ALPHAS[L]))
                c.set_visible(True)
        for c in self.smoke_circles[shown * n_layers:]:
            c.set_visible(False)

    def _update_flash(self, tick: float) -> None:
        data = self._flash
        active = self._active_idx(data, tick)
        shown = min(len(active), len(self.flash_circles))
        dur = max(self._seconds_to_ticks(self.config.flash_duration), 1)
        for c in self.flash_circles:
            c.set_visible(False)
        for j in range(shown):
            i = active[j]
            prog = min((tick - data["starts"][i]) / dur, 1.0)
            c = self.flash_circles[j]
            c.set_center((data["px"][i], data["py"][i]))
            c.set_radius(self.config.flash_radius * (0.7 + 0.3 * prog))
            c.set_facecolor(self.config.flash_color)
            c.set_alpha(self._scaled(max(0.9 * (1.0 - prog), 0.0)))
            c.set_visible(True)
        for c in self.flash_circles[shown:]:
            c.set_visible(False)

    def _update_he(self, tick: float) -> None:
        data = self._he
        active = self._active_idx(data, tick)
        shown = min(len(active), len(self.he_circles))
        dur = max(self._seconds_to_ticks(self.config.he_duration), 1)
        for c in self.he_circles:
            c.set_visible(False)
        for j in range(shown):
            i = active[j]
            prog = min((tick - data["starts"][i]) / dur, 1.0)
            c = self.he_circles[j]
            c.set_center((data["px"][i], data["py"][i]))
            c.set_radius(self.config.he_radius * (0.5 + 0.5 * prog))
            c.set_edgecolor(self.config.he_color)
            c.set_facecolor("none")
            c.set_linewidth(3.0)
            c.set_alpha(self._scaled(max(0.9 * (1.0 - prog), 0.0)))
            c.set_visible(True)
        for c in self.he_circles[shown:]:
            c.set_visible(False)

    def _update_fire(self, tick: float) -> None:
        data = self._fire
        active = self._active_idx(data, tick)
        n_flames = _N_FIRE_FLAMES
        shown = min(len(active), len(self.fire_flame_marks) // n_flames)
        for m in self.fire_flame_marks:
            m.set_alpha(0)
        for c in self.fire_circles:
            c.set_visible(False)
        for j in range(shown):
            i = active[j]
            age = tick - data["starts"][i]
            dur = max(data["durs"][i], 1)
            base_r = self.config.fire_radius * (0.8 + 0.2 * min(age / 10.0, 1.0))
            if age < dur - 5:
                base_a = 0.55
            else:
                base_a = 0.55 * max((dur - age) / 5.0, 0.0)
            cx, cy = data["px"][i], data["py"][i]
            # faint persistent base zone under the flickering flames
            c = self.fire_circles[j]
            c.set_center((cx, cy))
            c.set_radius(base_r)
            c.set_facecolor(self.config.fire_color)
            c.set_alpha(self._scaled(base_a * 0.45))
            c.set_visible(True)
            # flickering flame cluster: scattered points whose alpha/size/position
            # jitter on sine waves (per-event phase) so the fire visibly burns.
            for f in range(n_flames):
                m = self.fire_flame_marks[j * n_flames + f]
                ox, oy = self._fire_offsets[i, f]
                phase = self._fire_phases[i, f]
                drift = base_r * 0.10
                dx = base_r * ox + np.sin(2 * np.pi * age / 11.0 + phase) * drift
                dy = base_r * oy + np.cos(2 * np.pi * age / 9.0 + phase) * drift
                m.set_data([cx + dx], [cy + dy])
                flick = 0.55 + 0.45 * abs(np.sin(2 * np.pi * age / 5.0 + phase))
                m.set_color(self.config.fire_color)
                m.set_markersize(5 + 4 * flick)
                m.set_alpha(self._scaled(base_a * flick))
                m.set_visible(True)
        for c in self.fire_circles[shown:]:
            c.set_visible(False)
        # molly impact ring
        mdata = self._molly
        mact = self._active_idx(mdata, tick)
        mshown = min(len(mact), len(self.molly_circles))
        for c in self.molly_circles:
            c.set_visible(False)
        for j in range(mshown):
            i = mact[j]
            prog = min((tick - mdata["starts"][i]) / max(self._seconds_to_ticks(2.0), 1), 1.0)
            c = self.molly_circles[j]
            c.set_center((mdata["px"][i], mdata["py"][i]))
            c.set_radius(60.0 * prog)
            c.set_edgecolor(self.config.molly_color)
            c.set_facecolor("none")
            c.set_linewidth(2.5)
            c.set_alpha(self._scaled(max(0.8 * (1.0 - prog), 0.0)))
            c.set_visible(True)
        for c in self.molly_circles[mshown:]:
            c.set_visible(False)

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
            m.set_alpha(self._scaled(1.0 - prog * 0.7))
            m.set_visible(True)

    def _update_jump_rings(self, tick: float) -> None:
        data = self._jumps
        for c in self.jump_rings:
            c.set_visible(False)
        active = self._active_idx(data, tick)
        shown = min(len(active), len(self.jump_rings))
        win = self._seconds_to_ticks(self.config.jump_ring_seconds)
        for j in range(shown):
            i = active[j]
            prog = min(max((tick - data["starts"][i]) / max(win, 1), 0.0), 1.0)
            c = self.jump_rings[j]
            c.set_center((data["px"][i], data["py"][i]))
            c.set_radius(20.0 + 60.0 * prog)
            c.set_alpha(self._scaled(max(0.75 * (1.0 - prog), 0.0)))
            c.set_visible(True)
        for c in self.jump_rings[shown:]:
            c.set_visible(False)

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
            km.set_alpha(self._scaled(alpha))
            vm.set_alpha(self._scaled(alpha))
            line.set_alpha(self._scaled(alpha))
