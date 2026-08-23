"""2D replay renderer: animate a player's full action timeline on the map.

Manual frame loop + FFMpegWriter (streaming to ffmpeg stdin), NOT FuncAnimation:
robust for thousands of frames, deterministic frame count, easy progress/failure
diagnosis. Playback modes: full match (fast-forward), highlight rounds, and
time-driven path overlays (openings / full overlap).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FFMpegWriter
from matplotlib.collections import LineCollection

from cs_analyzer.config import ReplayConfig
from cs_analyzer.maps import MapResource, load_map_or_fallback
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.replay.timeline import PlayerTimeline, build_timeline, round_freeze_ends
from cs_analyzer.render.effects import EffectManager
from cs_analyzer.render.fonts import setup_fonts
from cs_analyzer.render.hud import ReplayHUD
from cs_analyzer.utils.ffmpeg import find_ffmpeg

logger = logging.getLogger(__name__)

# World-units gap between consecutive ticks treated as a teleport (respawn /
# round-to-round jump). A player moving at 64 tick moves < ~10 units/tick.
_BREAK_DISTANCE = 300.0


def build_trail_segments(wx, wy, break_distance: float = _BREAK_DISTANCE) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Build line-segment pairs from world points, dropping pairs that span a
    teleport (respawn / round jump) so spawn points are never connected."""
    if len(wx) < 2:
        return []
    dist = np.hypot(np.diff(wx), np.diff(wy))
    return [
        ((wx[i], wy[i]), (wx[i + 1], wy[i + 1]))
        for i in range(len(wx) - 1) if dist[i] < break_distance
    ]


@dataclass
class Segment:
    start_tick: int
    end_tick: int
    speed: float
    label: str
    n_frames: int = 0

    @property
    def duration_ticks(self) -> int:
        return max(self.end_tick - self.start_tick, 1)


class ReplayAnimationRenderer:
    """Render a player's 2D replay to MP4."""

    def __init__(
        self,
        config: ReplayConfig,
        demo: ParsedDemo,
        map_resource: MapResource | None = None,
    ) -> None:
        self.config = config
        self.demo = demo
        if map_resource is None:
            map_resource = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
        self.map = map_resource

    # ---- public API ----

    def render_player(
        self,
        steamid_or_name: str,
        output_path: str | Path,
        mode: str = "all",
        speed: float | None = None,
        rounds: list[int] | None = None,
        opening: float | None = None,
        tick_rate: int = 64,
    ) -> Path:
        """Render a player replay video.

        mode: "all" (full match), "highlights" (selected rounds),
              "openings" / "overlap-full" (time-driven path overlays).
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        setup_fonts(self.config.font)

        timeline = build_timeline(
            self.demo, steamid_or_name, nade_flight_seconds=self.config.nade_flight_seconds
        )

        if mode == "openings":
            windows = self._opening_windows(timeline, opening, tick_rate)
            return self._render_overlay(timeline, windows, output_path, speed, tick_rate,
                                        "开局路径重叠 30s", aligned=True)
        if mode == "overlap-full":
            windows = self._full_windows(timeline)
            return self._render_overlay(timeline, windows, output_path, speed, tick_rate, "全场路径重叠")

        segments = self._build_segments(timeline, mode, speed, rounds, opening, tick_rate)
        if not segments:
            raise ValueError("No segments to render (empty selection or no rounds).")
        self._assign_frame_counts(segments, tick_rate)

        total_frames = sum(s.n_frames for s in segments)
        if self.config.round_end_hold_seconds > 0:
            total_frames += int(self.config.fps * self.config.round_end_hold_seconds) * len(segments)
        if total_frames > self.config.max_frames:
            raise ValueError(
                f"Render would produce {total_frames} frames (cap {self.config.max_frames}). "
                "Increase speed or narrow the selection."
            )
        logger.info("replay %s: %d segments, %d frames", timeline.player.name, len(segments), total_frames)

        return self._render_continuous(timeline, segments, output_path, tick_rate)

    # ---- segment building ----

    def _build_segments(
        self,
        timeline: PlayerTimeline,
        mode: str,
        speed: float | None,
        rounds: list[int] | None,
        opening: float | None,
        tick_rate: int,
    ) -> list[Segment]:
        regular = self.demo.regular_rounds
        if mode == "highlights":
            selected = [r for r in regular if rounds is None or r.number in rounds]
            spd = speed if speed is not None else self.config.speed_highlight
            return [Segment(r.start_tick, r.end_tick, spd, f"R{r.number}") for r in selected]
        # "all"
        spd = speed if speed is not None else self.config.speed_full
        return [Segment(r.start_tick, r.end_tick, spd, f"R{r.number}") for r in regular]

    def _assign_frame_counts(self, segments: list[Segment], tick_rate: int) -> None:
        for seg in segments:
            ticks_per_frame = tick_rate * seg.speed / self.config.fps
            seg.n_frames = max(int(seg.duration_ticks / ticks_per_frame), 1)

    # ---- overlay windows (overlap round paths, color-coded) ----

    def _opening_windows(
        self, timeline: PlayerTimeline, opening: float | None, tick_rate: int
    ) -> list[tuple[int, int, int]]:
        """Per-round opening windows: [freeze_end, freeze_end + opening], clamped
        to the player's alive end (prep/death time trimmed)."""
        freeze = round_freeze_ends(self.demo)
        open_ticks = int((opening if opening is not None else self.config.opening_seconds) * tick_rate)
        windows = []
        for r in self.demo.regular_rounds:
            fe = freeze.get(r.number, r.start_tick)
            start, alive_end = timeline.alive_window(r, fe)
            end = min(r.end_tick, start + open_ticks, alive_end)
            if end > start:
                windows.append((r.number, start, end))
        return windows

    def _full_windows(self, timeline: PlayerTimeline) -> list[tuple[int, int, int]]:
        """Per-round full alive windows (prep + death time trimmed)."""
        freeze = round_freeze_ends(self.demo)
        windows = []
        for r in self.demo.regular_rounds:
            fe = freeze.get(r.number, r.start_tick)
            start, end = timeline.alive_window(r, fe)
            if end > start:
                windows.append((r.number, start, end))
        return windows

    def _render_overlay(
        self,
        timeline: PlayerTimeline,
        windows: list[tuple[int, int, int]],
        output_path: Path,
        speed: float | None,
        tick_rate: int,
        title: str,
        aligned: bool = False,
    ) -> Path:
        """Time-driven overlay: advance a game tick through the windows while the
        player's actions animate (projectiles/smoke/kills via EffectManager) and
        each window's path grows to the current tick. Holds the full overlay at
        the end for comparison.

        aligned=True (openings): windows all start at different absolute ticks but
        represent the same relative window (e.g. first 30s of each round). Advance
        a LOCAL offset and remap effects to local ticks so rounds are compared
        simultaneously. aligned=False (full overlap): advance the global tick.
        """
        if not windows:
            raise ValueError("No windows to overlay.")
        spd = speed if speed is not None else (
            self.config.speed_overlay if aligned else self.config.speed_full
        )
        if aligned:
            span = max(w[2] - w[1] for w in windows)
            t0 = 0.0
            effects_view = self._local_offset_view(timeline, windows)
        else:
            t0 = min(w[1] for w in windows)
            span = max(w[2] for w in windows) - t0
            effects_view = timeline
        n_frames = max(int(span / (tick_rate * spd / self.config.fps)), 1)
        hold_frames = int(self.config.fps * self.config.overlay_hold_seconds)
        fade_frames = min(int(self.config.fps * self.config.overlay_fade_seconds), hold_frames)

        fig, ax, round_lines, round_labels, spawns = self._setup_overlay_figure(timeline, windows, title)
        effects = EffectManager(self.config, effects_view, self.map, tick_rate=tick_rate)
        effects.attach(ax)
        hud = ReplayHUD(self.config, timeline, self.demo)
        hud.attach(fig, ax)

        writer = self._make_writer()
        try:
            with writer.saving(fig, str(output_path), dpi=self.config.dpi):
                for i in range(n_frames + hold_frames):
                    p = min(i / max(n_frames - 1, 1), 1.0)
                    for k, (rnum, wstart, wend) in enumerate(windows):
                        line = round_lines[k]
                        if aligned:
                            # local offset -> absolute tick within this window
                            local = p * (wend - wstart)
                            a, b = wstart, wstart + local
                            if local < 1:
                                line.set_visible(False)
                                continue
                        else:
                            t = t0 + p * span
                            if t < wstart:
                                line.set_visible(False)
                                continue
                            a, b = wstart, min(t, wend)
                        lo = int(np.searchsorted(timeline.ticks, a, side="left"))
                        hi = int(np.searchsorted(timeline.ticks, b, side="right"))
                        if hi - lo < 2:
                            line.set_visible(False)
                            continue
                        idx = np.arange(lo, hi)
                        wx = timeline.xs[idx]
                        wy = timeline.ys[idx]
                        px, py = self.map.world_to_pixel_array(wx, wy)
                        line.set_data(px, py)
                        line.set_visible(True)
                    if i >= n_frames:
                        # fade the finished overlay out before the video ends
                        held = i - n_frames
                        prog = held / max(fade_frames, 1) if held < fade_frames else 1.0
                        alpha = max(0.85 * (1.0 - prog), 0.0)
                        for line in round_lines:
                            if line.get_visible():
                                line.set_alpha(alpha)
                        effects.set_alpha_scale(max(1.0 - prog, 0.0))  # V1: effects fade too
                    else:
                        effects.set_alpha_scale(1.0)
                    if aligned:
                        effects.update(p * span)
                    else:
                        effects.update(t)
                        rnd = self.demo.data.round_at_tick(int(t))
                        if rnd is not None:
                            hud.update(t, rnd.number, timeline.side_for_round(rnd), title)
                    writer.grab_frame()
        finally:
            plt.close(fig)
        logger.info("replay overlay -> %s", output_path)
        return output_path

    def _local_offset_view(self, timeline: PlayerTimeline, windows):
        """Duck-typed timeline whose effect ticks are local offsets within the
        aligned windows (so a shared local tick drives all rounds' effects)."""
        from dataclasses import replace

        def local_of(tick):
            for _, s, e in windows:
                if s <= tick < e:
                    return tick - s
            return None

        class View:
            pass

        view = View()
        view.utilities = {}
        for kind, evs in timeline.utilities.items():
            out = []
            for e in evs:
                loc = local_of(e.tick)
                if loc is None:
                    continue
                kwargs = {}
                if hasattr(e, "throw_tick") and e.throw_tick >= 0:
                    kwargs["throw_tick"] = e.throw_tick - e.tick + loc
                out.append(replace(e, tick=loc, **kwargs))
            out.sort(key=lambda e: e.tick)
            view.utilities[kind] = out
        view.kills = []
        for k in timeline.kills:
            loc = local_of(k.tick)
            if loc is not None:
                view.kills.append(replace(k, tick=loc))
        view.kills.sort(key=lambda k: k.tick)
        view.shots = [replace(s, tick=local_of(s.tick)) for s in timeline.shots if local_of(s.tick) is not None]
        view.shots.sort(key=lambda e: e.tick)
        view.jumps = [replace(j, tick=local_of(j.tick)) for j in timeline.jumps if local_of(j.tick) is not None]
        view.jumps.sort(key=lambda e: e.tick)
        view.deaths = [replace(d, tick=local_of(d.tick)) for d in timeline.deaths if local_of(d.tick) is not None]
        view.deaths.sort(key=lambda e: e.tick)
        return view

    def _setup_overlay_figure(self, timeline: PlayerTimeline, windows, title: str):
        fig, ax = plt.subplots(
            figsize=(self.config.width / self.config.dpi, self.config.height / self.config.dpi),
            dpi=self.config.dpi,
        )
        fig.patch.set_facecolor(self.config.bg_color)
        ax.set_facecolor(self.config.bg_color)
        if self.map.image_path is not None:
            img = plt.imread(str(self.map.image_path))
            ax.imshow(img, extent=[0, self.map.image_width, self.map.image_height, 0], origin="upper")
        else:
            ax.set_xlim(0, self.map.image_width)
            ax.set_ylim(self.map.image_height, 0)
        ax.set_aspect("equal")
        ax.axis("off")

        cmap = plt.get_cmap("tab20")
        round_lines = []
        round_labels = []
        spawns = []
        for k, (rnum, start, _) in enumerate(windows):
            color = cmap(k % 20)
            (line,) = ax.plot([], [], color=color, linewidth=2.0, alpha=0.85, zorder=5)
            round_lines.append(line)
            # label the round number at its opening start position
            lo = int(np.searchsorted(timeline.ticks, start, side="left"))
            if lo < len(timeline.ticks):
                wx, wy = timeline.xs[lo], timeline.ys[lo]
                px, py = self.map.world_to_pixel(wx, wy)
                txt = ax.text(px, py, str(rnum), color=color, fontsize=9, weight="bold",
                              ha="center", va="center", zorder=9)
                round_labels.append(txt)
                spawns.append((px, py))
            else:
                round_labels.append(None)
                spawns.append(None)

        ax.text(self.map.image_width / 2, 12, title, color="white",
                fontsize=16, ha="center", va="top", zorder=20)
        return fig, ax, round_lines, round_labels, spawns

    # ---- continuous render ----

    def _render_continuous(
        self,
        timeline: PlayerTimeline,
        segments: list[Segment],
        output_path: Path,
        tick_rate: int,
        single_segment: bool = False,
    ) -> Path:
        fig, ax, ctx = self._setup_figure(timeline)
        writer = self._make_writer()
        ffmpeg = find_ffmpeg()
        try:
            with writer.saving(fig, str(output_path), dpi=self.config.dpi):
                frame_no = 0
                for seg in segments:
                    frame_ticks = (
                        seg.start_tick + np.arange(seg.n_frames) * (tick_rate * seg.speed / self.config.fps)
                    )
                    xs, ys, alive = timeline.frame_positions(frame_ticks)
                    px, py = self.map.world_to_pixel_array(xs, ys)
                    for i in range(seg.n_frames):
                        tick = float(frame_ticks[i])
                        self._update_frame(fig, ax, ctx, timeline, seg, tick,
                                           float(px[i]), float(py[i]), bool(alive[i]), tick_rate)
                        writer.grab_frame()
                        frame_no += 1
                        if frame_no % 200 == 0:
                            logger.info("replay frame %d/%d", frame_no, sum(s.n_frames for s in segments))
                    if self.config.round_end_hold_seconds > 0:
                        hold_frames = int(self.config.fps * self.config.round_end_hold_seconds)
                        self._hold_and_fade(writer, ctx, tick, hold_frames,
                                            self._winner_for_segment(seg))
        except Exception:
            logger.error("replay render failed at %s", output_path)
            raise
        finally:
            plt.close(fig)
        logger.info("replay -> %s", output_path)
        return output_path

    def _hold_and_fade(self, writer, ctx, tick: float, hold_frames: int, winner_side: str | None) -> None:
        """Round-end pause: show the winner banner, then fade the trail + effects
        before the next round (V2/V3)."""
        banner = ctx.get("winner_banner")
        show_banner = None
        if winner_side is not None and self.config.show_winner_banner:
            show_banner = banner
            banner.set_text(f"{winner_side} 获胜")
            banner.set_color(self.config.t_color if winner_side == "T" else self.config.ct_color)
            banner.set_visible(True)
        fade_frames = min(int(self.config.fps * self.config.overlay_fade_seconds), hold_frames)
        for h in range(hold_frames):
            if h >= hold_frames - fade_frames:
                prog = (h - (hold_frames - fade_frames)) / max(fade_frames, 1)
                a = max(1.0 - prog, 0.0)
            else:
                a = 1.0
            ctx["trail_collection"].set_alpha(a)
            ctx["effects"].set_alpha_scale(a)
            ctx["effects"].update(tick)
            if show_banner is not None:
                show_banner.set_alpha(a)
                show_banner.set_visible(a > 0)
            writer.grab_frame()
        ctx["effects"].set_alpha_scale(1.0)
        if show_banner is not None:
            show_banner.set_visible(False)

    def _winner_for_segment(self, seg: Segment) -> str | None:
        rnd = self.demo.data.round_at_tick(max(seg.end_tick - 1, seg.start_tick))
        return rnd.winner_side if rnd else None

    def _make_writer(self) -> FFMpegWriter:
        matplotlib.rcParams["animation.ffmpeg_path"] = find_ffmpeg()
        return FFMpegWriter(
            fps=self.config.fps,
            codec="libx264",
            extra_args=["-pix_fmt", "yuv420p", "-crf", "18"],
        )

    def _setup_figure(self, timeline: PlayerTimeline):
        fig, ax = plt.subplots(
            figsize=(self.config.width / self.config.dpi, self.config.height / self.config.dpi),
            dpi=self.config.dpi,
        )
        fig.patch.set_facecolor(self.config.bg_color)
        ax.set_facecolor(self.config.bg_color)

        if self.map.image_path is not None:
            img = plt.imread(str(self.map.image_path))
            ax.imshow(img, extent=[0, self.map.image_width, self.map.image_height, 0], origin="upper")
        else:
            ax.set_xlim(0, self.map.image_width)
            ax.set_ylim(self.map.image_height, 0)
        ax.set_aspect("equal")
        ax.axis("off")

        # Trail as a LineCollection: per-segment color/alpha (recency fade) and
        # breaks at teleports (respawn / round jump) — never connects spawn points.
        trail_col = LineCollection([], zorder=4)
        trail_col.set_visible(False)
        ax.add_collection(trail_col)

        player_marker, = ax.plot([], [], "o", color="white",
                                 markersize=self.config.player_marker_size,
                                 markeredgecolor=self.config.player_marker_edge,
                                 markeredgewidth=1.0, zorder=8)
        player_marker.set_color(self.config.t_color)

        # Effects + HUD.
        effects = EffectManager(self.config, timeline, self.map, tick_rate=64)
        effects.attach(ax)
        hud = ReplayHUD(self.config, timeline, self.demo)
        hud.attach(fig, ax)

        winner_banner = fig.text(0.5, 0.965, "", color="white", fontsize=18, weight="bold",
                                 ha="center", va="top", transform=fig.transFigure, zorder=30)
        winner_banner.set_visible(False)

        ctx = {
            "trail_collection": trail_col,
            "player_marker": player_marker,
            "effects": effects,
            "hud": hud,
            "winner_banner": winner_banner,
        }
        return fig, ax, ctx

    def _update_frame(
        self, fig, ax, ctx, timeline: PlayerTimeline, seg: Segment, tick: float,
        px: float, py: float, alive: bool, tick_rate: int,
    ) -> None:
        side = timeline.side_at_tick(tick)
        trail_col = ctx["trail_collection"]
        # Trail: points within an output-time window scaled to game ticks.
        window_ticks = int(self.config.trail_seconds * tick_rate * seg.speed)
        window_ticks = max(window_ticks, 1)
        lo = int(np.searchsorted(timeline.ticks, tick - window_ticks, side="left"))
        hi = int(np.searchsorted(timeline.ticks, tick, side="right"))
        if hi - lo >= 2:
            idx = np.arange(lo, hi)
            wx = timeline.xs[idx]
            wy = timeline.ys[idx]
            px, py = self.map.world_to_pixel_array(wx, wy)
            # Drop segment pairs that span a teleport (respawn / round jump).
            segs = build_trail_segments(wx, wy, self.config.break_distance)
            if segs:
                segs = [
                    (self.map.world_to_pixel(x0, y0), self.map.world_to_pixel(x1, y1))
                    for (x0, y0), (x1, y1) in segs
                ]
                base = np.asarray(mcolors.to_rgba(self.config.t_color if side == "T" else self.config.ct_color))
                n = len(segs)
                rgba = np.tile(base, (n, 1))
                rgba[:, 3] = np.linspace(self.config.trail_alpha_min, self.config.trail_alpha_max, n)
                trail_col.set_segments(segs)
                trail_col.set_color(rgba)
                trail_col.set_linewidths(np.linspace(self.config.trail_width_min, self.config.trail_width_max, n))
                trail_col.set_visible(True)
            else:
                trail_col.set_segments([])
                trail_col.set_visible(False)
        else:
            trail_col.set_segments([])
            trail_col.set_visible(False)

        # Player marker.
        marker = ctx["player_marker"]
        if alive:
            marker.set_data([px], [py])
            marker.set_color(self.config.t_color if side == "T" else self.config.ct_color)
            marker.set_alpha(1.0)
        else:
            marker.set_data([px], [py])
            marker.set_alpha(0.35)

        ctx["effects"].update(tick)

        if self.config.hud_enabled:
            rnd = self.demo.data.round_at_tick(int(tick))
            round_no = rnd.number if rnd else 0
            ctx["hud"].update(tick, round_no, side, seg.label)
