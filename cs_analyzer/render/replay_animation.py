"""2D replay renderer: animate a player's full action timeline on the map.

Manual frame loop + FFMpegWriter (streaming to ffmpeg stdin), NOT FuncAnimation:
robust for thousands of frames, deterministic frame count, easy progress/failure
diagnosis. Supports three playback modes: full match (fast-forward), highlight
rounds, and a round-openings montage (per-round clips concatenated).
"""
from __future__ import annotations

import logging
import subprocess
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
from cs_analyzer.replay.timeline import PlayerTimeline, build_timeline
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

        mode: "all" (full match), "highlights" (selected rounds), "montage"
              (each round's opening window, concatenated).
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        setup_fonts(self.config.font)

        timeline = build_timeline(self.demo, steamid_or_name)

        if mode == "openings":
            return self._render_openings(timeline, output_path, opening, speed, tick_rate)

        segments = self._build_segments(timeline, mode, speed, rounds, opening, tick_rate)
        if not segments:
            raise ValueError("No segments to render (empty selection or no rounds).")
        self._assign_frame_counts(segments, tick_rate)

        total_frames = sum(s.n_frames for s in segments)
        if total_frames > self.config.max_frames:
            raise ValueError(
                f"Render would produce {total_frames} frames (cap {self.config.max_frames}). "
                "Increase speed or narrow the selection."
            )
        logger.info("replay %s: %d segments, %d frames", timeline.player.name, len(segments), total_frames)

        if mode == "montage":
            return self._render_montage(timeline, segments, output_path, tick_rate)
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
        if mode == "montage":
            open_sec = opening if opening is not None else self.config.montage_open_seconds
            open_ticks = int(open_sec * tick_rate)
            segs = []
            for rnd in regular:
                end = min(rnd.end_tick, rnd.start_tick + open_ticks)
                segs.append(Segment(rnd.start_tick, end, self.config.speed_montage, f"R{rnd.number}"))
            return segs
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

    # ---- montage (per-round clips + concat) ----

    def _render_montage(
        self, timeline: PlayerTimeline, segments: list[Segment], output_path: Path, tick_rate: int
    ) -> Path:
        tmp_dir = output_path.parent / f".{output_path.stem}_parts"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        parts: list[Path] = []
        try:
            for i, seg in enumerate(segments):
                part = tmp_dir / f"part_{i:03d}.mp4"
                self._render_continuous(timeline, [seg], part, tick_rate, single_segment=True)
                parts.append(part)
            self._concat_parts(parts, output_path)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return output_path

    @staticmethod
    def _concat_parts(parts: list[Path], output_path: Path) -> None:
        ffmpeg = find_ffmpeg()
        list_file = output_path.parent / f".{output_path.stem}_concat.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for p in parts:
                # Absolute paths: ffmpeg concat resolves relative paths against
                # the list file's directory, which would double the prefix.
                f.write(f"file '{str(p.resolve()).replace(chr(39), chr(39) * 2)}'\n")
        cmd = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(output_path),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        list_file.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-500:]}")

    # ---- openings mode (overlap round-opening paths, color-coded) ----

    def _render_openings(
        self,
        timeline: PlayerTimeline,
        output_path: Path,
        opening: float | None,
        speed: float | None,
        tick_rate: int,
    ) -> Path:
        """Overlay each round's opening window on one map, one color per round.

        All rounds' first `opening` game-seconds draw simultaneously (progressively
        revealed), each in a distinct color, so routes between rounds are compared.
        """
        open_ticks = int((opening if opening is not None else self.config.montage_open_seconds) * tick_rate)
        rounds = self.demo.regular_rounds
        windows = [
            (r.number, r.start_tick, min(r.end_tick, r.start_tick + open_ticks))
            for r in rounds
            if r.end_tick > r.start_tick
        ]
        if not windows:
            raise ValueError("No rounds with opening windows to overlay.")

        spd = speed if speed is not None else self.config.speed_montage
        n_frames = max(int(open_ticks / (tick_rate * spd / self.config.fps)), 1)
        hold_frames = int(self.config.fps * 3)  # hold the full overlay after the reveal

        fig, ax, round_lines, round_labels, spawns = self._setup_openings_figure(timeline, windows)
        # Precompute each round's timeline index range.
        idx_ranges = []
        for _, start, end in windows:
            lo = int(np.searchsorted(timeline.ticks, start, side="left"))
            hi = int(np.searchsorted(timeline.ticks, end, side="right"))
            idx_ranges.append((lo, hi))

        writer = self._make_writer()
        try:
            with writer.saving(fig, str(output_path), dpi=self.config.dpi):
                for i in range(n_frames + hold_frames):
                    progress = min(i / max(n_frames - 1, 1), 1.0)
                    for k, ((_, start, _), (lo, hi)) in enumerate(zip(windows, idx_ranges)):
                        line = round_lines[k]
                        if hi - lo < 2:
                            line.set_visible(False)
                            continue
                        reveal = max(int(progress * (hi - lo)), 2)
                        seg = np.arange(lo, lo + reveal)
                        wx = timeline.xs[seg]
                        wy = timeline.ys[seg]
                        px, py = self.map.world_to_pixel_array(wx, wy)
                        line.set_data(px, py)
                        line.set_visible(True)
                    writer.grab_frame()
        finally:
            plt.close(fig)
        logger.info("replay openings -> %s", output_path)
        return output_path

    def _setup_openings_figure(self, timeline: PlayerTimeline, windows):
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

        title = ax.text(self.map.image_width / 2, 12, "开局路径重叠", color="white",
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
        except Exception:
            logger.error("replay render failed at %s", output_path)
            raise
        finally:
            plt.close(fig)
        logger.info("replay -> %s", output_path)
        return output_path

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

        player_marker, = ax.plot([], [], "o", color="white", markersize=9, markeredgecolor="black",
                                 markeredgewidth=1.0, zorder=8)
        player_marker.set_color(self.config.t_color)

        # Effects + HUD.
        effects = EffectManager(self.config, timeline, self.map, tick_rate=64)
        effects.attach(ax)
        hud = ReplayHUD(self.config, timeline, self.demo)
        hud.attach(fig, ax)

        ctx = {
            "trail_collection": trail_col,
            "player_marker": player_marker,
            "effects": effects,
            "hud": hud,
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
            segs = build_trail_segments(wx, wy)
            if segs:
                segs = [
                    (self.map.world_to_pixel(x0, y0), self.map.world_to_pixel(x1, y1))
                    for (x0, y0), (x1, y1) in segs
                ]
                base = np.asarray(mcolors.to_rgba(self.config.t_color if side == "T" else self.config.ct_color))
                n = len(segs)
                rgba = np.tile(base, (n, 1))
                rgba[:, 3] = np.linspace(0.15, 1.0, n)  # recency fade
                trail_col.set_segments(segs)
                trail_col.set_color(rgba)
                trail_col.set_linewidths(np.linspace(1.2, 3.5, n))
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
