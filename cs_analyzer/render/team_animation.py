"""Team replay renderer: all players on the map simultaneously.

Shows every player's trail + marker in a distinct color, corpses (skull) for
players dead in the current round, kill connections, and every player's
utilities. Prep/freeze time is trimmed via round_freeze_end.
"""
from __future__ import annotations

import logging
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
from cs_analyzer.replay.timeline import build_timeline, round_freeze_ends
from cs_analyzer.render.effects import EffectManager
from cs_analyzer.render.fonts import setup_fonts
from cs_analyzer.utils.ffmpeg import find_ffmpeg

logger = logging.getLogger(__name__)

_BREAK_DISTANCE = 300.0
_SKULL = "$☠$"


class TeamReplayRenderer:
    def __init__(self, config: ReplayConfig, demo: ParsedDemo) -> None:
        self.config = config
        self.demo = demo
        self.tick_rate = 64
        self.map: MapResource = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
        self.freeze = round_freeze_ends(demo)

        # ---- build per-player timelines (skip players lacking position data) ----
        self.timelines = []
        for p in demo.players:
            try:
                tl = build_timeline(
                    demo, p.steamid, nade_flight_seconds=config.nade_flight_seconds
                )
            except ValueError:
                logger.warning("team: skipping %s (no position data)", p.name)
                continue
            if len(tl.ticks) == 0:  # untracked player (no ticks at all)
                logger.warning("team: skipping %s (empty position ticks)", p.name)
                continue
            self.timelines.append(tl)

        self.all_kills = []
        self.team_utils: dict[str, list] = {}
        for tl in self.timelines:
            self.all_kills.extend(tl.kills)
            for kind, evs in tl.utilities.items():
                self.team_utils.setdefault(kind, []).extend(evs)
        self.all_kills.sort(key=lambda k: k.tick)
        for kind in self.team_utils:
            self.team_utils[kind].sort(key=lambda e: e.tick)  # searchsorted needs sorted starts

        # Team color families: T = yellows, CT = blues (shade varies per player).
        self.colors = []
        t_idx = ct_idx = 0
        for tl in self.timelines:
            if tl.starting_side == "T":
                self.colors.append(mcolors.to_rgba(config.t_palette[t_idx % len(config.t_palette)]))
                t_idx += 1
            else:
                self.colors.append(mcolors.to_rgba(config.ct_palette[ct_idx % len(config.ct_palette)]))
                ct_idx += 1
        self.steamids = [tl.player.steamid for tl in self.timelines]

    # ---- segments: per round [freeze_end, round_end] ----

    def _segments(self, rounds: list[int] | None, speed: float | None) -> list[tuple[int, int, int, float]]:
        spd = speed if speed is not None else self.config.speed_team
        segs = []
        for r in self.demo.regular_rounds:
            if rounds is not None and r.number not in rounds:
                continue
            start = self.freeze.get(r.number, r.start_tick)
            if r.end_tick > start:
                segs.append((r.number, start, r.end_tick, spd))
        return segs

    # ---- public API ----

    def render(
        self,
        output_path: str | Path,
        rounds: list[int] | None = None,
        speed: float | None = None,
        highlight_steamid: str | None = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        setup_fonts(self.config.font)
        self.highlight_idx = self._index_of(highlight_steamid) if highlight_steamid else -1
        segs = self._segments(rounds, speed)
        if not segs:
            raise ValueError("No rounds to render for the team replay.")

        fig, ax, ctx = self._setup_figure()
        writer = self._make_writer()
        hold_round = int(self.config.fps * self.config.round_end_hold_seconds)
        total_frames = 0
        seg_frame_counts = []
        for _, start, end, spd in segs:
            n = max(int((end - start) / (self.tick_rate * spd / self.config.fps)), 1)
            seg_frame_counts.append(n)
            total_frames += n
        total_frames += hold_round * len(segs)
        if total_frames > self.config.max_frames:
            raise ValueError(
                f"Team render would produce {total_frames} frames (cap {self.config.max_frames}). "
                "Increase speed or narrow the selection."
            )
        logger.info("team replay: %d players, %d segments, %d frames",
                    len(self.timelines), len(segs), total_frames)
        try:
            with writer.saving(fig, str(output_path), dpi=self.config.dpi):
                frame_no = 0
                for (rnum, start, end, spd), n_frames in zip(segs, seg_frame_counts):
                    frame_ticks = start + np.arange(n_frames) * (self.tick_rate * spd / self.config.fps)
                    window_ticks = max(int(self.config.team_trail_seconds * self.tick_rate * spd), 1)
                    rng = (start, end)
                    # who is dead this round (corpse positions)
                    dead_info = []
                    for i, tl in enumerate(self.timelines):
                        dp = next((d for d in tl.deaths if rng[0] <= d.tick < rng[1]), None)
                        if dp is not None:
                            px, py = self.map.world_to_pixel(dp.x, dp.y)
                            dead_info.append((i, px, py))
                    # precompute segment positions for all players
                    all_px, all_py, alive_at = [], [], []
                    for tl in self.timelines:
                        xs, ys, alive = tl.frame_positions(frame_ticks)
                        px, py = self.map.world_to_pixel_array(xs, ys)
                        all_px.append(px)
                        all_py.append(py)
                        alive_at.append(alive)
                    for f in range(n_frames):
                        tick = float(frame_ticks[f])
                        px_f = [p[f] for p in all_px]
                        py_f = [p[f] for p in all_py]
                        al_f = [a[f] for a in alive_at]
                        self._update_frame(fig, ax, ctx, tick, rnum, rng,
                                           px_f, py_f, al_f, dead_info, window_ticks)
                        writer.grab_frame()
                        frame_no += 1
                        if frame_no % 200 == 0:
                            logger.info("team frame %d/%d", frame_no, total_frames)
                    if hold_round:
                        self._hold_and_fade(writer, ctx, tick, hold_round,
                                            self._winner_for_round(rnum))
        except Exception:
            logger.error("team render failed at %s", output_path)
            raise
        finally:
            plt.close(fig)
        logger.info("team replay -> %s", output_path)
        return output_path

    # ---- team overlays (T2a per-round / T2b whole-match) ----

    def render_overlay(
        self,
        output_path: str | Path,
        per_round: bool = True,
        speed: float | None = None,
    ) -> Path:
        """Time-driven team overlay with full action animation.

        per_round=True  (T2a): advance tick through each round; all players'
        paths grow to the current tick while every player's utilities and kills
        animate. Brief hold per round.
        per_round=False (T2b): advance tick through the whole match.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        setup_fonts(self.config.font)
        spd = speed if speed is not None else self.config.speed_team
        fig, ax, lines, markers, corpse_marks, rlabel, hud_ctx, banner = self._setup_overlay_axes()
        view = _TeamView(self.team_utils, self.all_kills)
        effects = EffectManager(self.config, view, self.map, tick_rate=self.tick_rate)
        effects.attach(ax)
        writer = self._make_writer()
        freeze = self.freeze
        hold_round = int(self.config.fps * self.config.round_end_hold_seconds)
        try:
            with writer.saving(fig, str(output_path), dpi=self.config.dpi):
                if per_round:
                    for r in self.demo.regular_rounds:
                        fe = freeze.get(r.number, r.start_tick)
                        t0, t1 = fe, r.end_tick
                        windows = self._round_player_windows(r, fe)
                        n = max(int((t1 - t0) / (self.tick_rate * spd / self.config.fps)), 1)
                        rlabel.set_text(f"回合 {r.number} · 团队走位 + 动作")
                        last_tick = t0
                        for f in range(n):
                            t = t0 + (t1 - t0) * f / n
                            self._overlay_frame(lines, markers, corpse_marks, windows, t)
                            effects.update(t)
                            self._overlay_hud(hud_ctx, t, r.number)
                            writer.grab_frame()
                            last_tick = t
                        self._fade_hold(writer, lines, markers, corpse_marks, effects,
                                        last_tick, hold_round, r.winner_side, banner)
                else:
                    t0 = min(freeze.get(r.number, r.start_tick) for r in self.demo.regular_rounds)
                    t1 = max(r.end_tick for r in self.demo.regular_rounds)
                    windows = [(tl, t0, t1) for tl in self.timelines]
                    n = max(int((t1 - t0) / (self.tick_rate * spd / self.config.fps)), 1)
                    if n + int(self.config.fps * 3) > self.config.max_frames:
                        raise ValueError(
                            f"team full overlay needs {n} frames (cap {self.config.max_frames}); "
                            "raise --speed"
                        )
                    rlabel.set_text("全场团队路径 + 动作")
                    last_tick = t0
                    for f in range(n):
                        t = t0 + (t1 - t0) * f / n
                        self._overlay_frame(lines, markers, corpse_marks, windows, t)
                        effects.update(t)
                        writer.grab_frame()
                        last_tick = t
                    self._fade_hold(writer, lines, markers, corpse_marks, effects,
                                    last_tick, int(self.config.fps * 3))
        except Exception:
            logger.error("team overlay render failed at %s", output_path)
            raise
        finally:
            plt.close(fig)
        logger.info("team overlay -> %s", output_path)
        return output_path

    def _round_player_windows(self, r, fe):
        """Per-player (timeline, start, alive_end) for one round."""
        windows = []
        for tl in self.timelines:
            dp = next((d for d in tl.deaths if fe <= d.tick < r.end_tick), None)
            end = dp.tick if dp is not None else r.end_tick
            windows.append((tl, fe, max(end, fe + 1)))
        return windows

    def _overlay_frame(self, lines, markers, corpse_marks, windows, t) -> None:
        for cm in corpse_marks:
            cm.set_alpha(0)
        for i, (line, marker, (tl, wstart, wend)) in enumerate(zip(lines, markers, windows)):
            if t < wstart:
                line.set_visible(False)
                marker.set_alpha(0)
                continue
            dead = t >= wend
            # V6: a player dead in this window -> their path turns gray
            line.set_color(self.config.dead_line_color if dead else self._overlay_colors[i])
            lo = int(np.searchsorted(tl.ticks, wstart, side="left"))
            hi = int(np.searchsorted(tl.ticks, min(t, wend), side="right"))
            if hi - lo < 2:
                line.set_visible(False)
                marker.set_alpha(0)
                continue
            idx = np.arange(lo, hi)
            px, py = self.map.world_to_pixel_array(tl.xs[idx], tl.ys[idx])
            line.set_data(px, py)
            line.set_alpha(0.85)  # reset after a previous round faded out
            line.set_visible(True)
            # position dot at the current tick (clamped to the alive window)
            cur = min(t, wend)
            cx = float(np.interp(cur, tl.ticks[idx], tl.xs[idx]))
            cy = float(np.interp(cur, tl.ticks[idx], tl.ys[idx]))
            mpx, mpy = self.map.world_to_pixel(cx, cy)
            if dead:
                marker.set_alpha(0)
                dp = next((d for d in tl.deaths if wstart <= d.tick <= wend), None)
                if dp is not None:
                    dpx, dpy = self.map.world_to_pixel(dp.x, dp.y)
                    corpse_marks[i].set_data([dpx], [dpy])
                    corpse_marks[i].set_alpha(1.0)
            else:
                marker.set_data([mpx], [mpy])
                marker.set_alpha(1.0)
                marker.set_visible(True)

    def _fade_hold(self, writer, lines, markers, corpse_marks, effects, last_tick: float,
                   hold_frames: int, winner_side: str | None = None, banner=None) -> None:
        """Hold the finished overlay (winner banner), then fade paths + effects out."""
        show_banner = None
        if winner_side is not None and self.config.show_winner_banner and banner is not None:
            show_banner = banner
            banner.set_text(f"{winner_side} 获胜")
            banner.set_color(self.config.t_color if winner_side == "T" else self.config.ct_color)
            banner.set_visible(True)
        fade_frames = min(int(self.config.fps * self.config.overlay_fade_seconds), hold_frames)
        for h in range(hold_frames):
            if h >= hold_frames - fade_frames:
                prog = (h - (hold_frames - fade_frames)) / max(fade_frames, 1)
                alpha = max(0.85 * (1.0 - prog), 0.0)
                es = max(1.0 - prog, 0.0)
            else:
                alpha = 0.85
                es = 1.0
            for line in lines:
                if line.get_visible():
                    line.set_alpha(alpha)
            for m in markers:
                if m.get_alpha() > 0:
                    m.set_alpha(alpha)
            for cm in corpse_marks:
                if cm.get_alpha() > 0:
                    cm.set_alpha(alpha)
            effects.set_alpha_scale(es)
            effects.update(last_tick)
            if show_banner is not None:
                show_banner.set_alpha(es)
                show_banner.set_visible(es > 0)
            writer.grab_frame()
        effects.set_alpha_scale(1.0)
        if show_banner is not None:
            show_banner.set_visible(False)

    def _hold_and_fade(self, writer, ctx, tick: float, hold_frames: int, winner_side: str | None) -> None:
        """Continuous render: pause per round-end with winner banner, then fade
        trails + effects before the next round (V2/V3)."""
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
            for tc in ctx["trail_cols"]:
                tc.set_alpha(a)
            ctx["effects"].set_alpha_scale(a)
            ctx["effects"].update(tick)
            if show_banner is not None:
                show_banner.set_alpha(a)
                show_banner.set_visible(a > 0)
            writer.grab_frame()
        ctx["effects"].set_alpha_scale(1.0)
        if show_banner is not None:
            show_banner.set_visible(False)

    def _winner_for_round(self, rnum: int) -> str | None:
        r = next((r for r in self.demo.regular_rounds if r.number == rnum), None)
        return r.winner_side if r else None

    def _overlay_hud(self, hud_ctx, tick, rnum) -> None:
        rnd = next((r for r in self.demo.regular_rounds if r.number == rnum), None)
        if rnd is None:
            return
        meta = self.demo.metadata
        hud_ctx["score"].set_text(f"{meta.team_b.name} {rnd.t_score} : {rnd.ct_score} {meta.team_a.name}")
        elapsed = (tick - rnd.start_tick) / self.tick_rate
        remain = max(self.config.round_clock_seconds - elapsed, 0)
        mm, ss = divmod(int(remain), 60)
        hud_ctx["clock"].set_text(f"{mm}:{ss:02d}")

    def _setup_overlay_axes(self):
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
        lines = [ax.plot([], [], color=c, linewidth=2.2, alpha=0.85, zorder=5)[0] for c in self.colors]
        self._overlay_colors = [l.get_color() for l in lines]  # V6 dead-line gray needs the original
        # player position dots + corpses, matching the continuous team render
        markers = [ax.plot([], [], "o", color=c, markersize=7, markeredgecolor="black",
                           markeredgewidth=0.6, alpha=0, zorder=8)[0] for c in self.colors]
        corpse_marks = [ax.plot([], [], marker=_SKULL, color="#FF3333", markersize=13,
                                linestyle="None", alpha=0, zorder=9)[0] for _ in self.colors]
        rlabel = ax.text(self.map.image_width / 2, 12, "", color="white",
                         fontsize=15, ha="center", va="top", zorder=20)
        score_text = fig.text(0.5, 0.97, "", color="white", fontsize=18, weight="bold",
                              ha="center", va="top", transform=fig.transFigure, zorder=20)
        clock_text = fig.text(0.98, 0.10, "", color="white", fontsize=20, weight="bold",
                              ha="right", va="bottom", transform=fig.transFigure, zorder=20)
        banner = fig.text(0.5, 0.965, "", color="white", fontsize=18, weight="bold",
                          ha="center", va="top", transform=fig.transFigure, zorder=30)
        banner.set_visible(False)
        hud_ctx = {"score": score_text, "clock": clock_text}
        return fig, ax, lines, markers, corpse_marks, rlabel, hud_ctx, banner

    # ---- figure / writer ----

    def _make_writer(self) -> FFMpegWriter:
        matplotlib.rcParams["animation.ffmpeg_path"] = find_ffmpeg()
        return FFMpegWriter(
            fps=self.config.fps,
            codec="libx264",
            extra_args=["-pix_fmt", "yuv420p", "-crf", "18"],
        )

    def _setup_figure(self):
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

        # per-player trails (LineCollection) + markers
        trail_cols, markers, corpse_marks = [], [], []
        for color in self.colors:
            tc = LineCollection([], zorder=4)
            tc.set_visible(False)
            ax.add_collection(tc)
            trail_cols.append(tc)
            (m,) = ax.plot([], [], "o", color=color, markersize=7,
                           markeredgecolor="black", markeredgewidth=0.6, zorder=8)
            markers.append(m)
            (cm,) = ax.plot([], [], marker=_SKULL, color="#FF3333", markersize=13,
                            linestyle="None", alpha=0, zorder=9)
            corpse_marks.append(cm)
        # white halo ring around the highlighted player
        halo = None
        if getattr(self, "highlight_idx", -1) >= 0:
            (halo,) = ax.plot([], [], "o", markersize=self.config.halo_size, markerfacecolor="none",
                              markeredgecolor="white", markeredgewidth=2.5,
                              linestyle="None", alpha=0, zorder=10)

        # effects: all players' utilities + all kill connections
        view = _TeamView(self.team_utils, self.all_kills)
        effects = EffectManager(self.config, view, self.map, tick_rate=self.tick_rate)
        effects.attach(ax)

        # simple team HUD: score / round / clock / player legend
        score_text = fig.text(0.5, 0.97, "", color="white", fontsize=20, weight="bold",
                              ha="center", va="top", transform=fig.transFigure, zorder=20)
        round_text = fig.text(0.98, 0.97, "", color="#CCCCCC", fontsize=16,
                              ha="right", va="top", transform=fig.transFigure, zorder=20)
        clock_text = fig.text(0.98, 0.12, "", color="white", fontsize=22, weight="bold",
                              ha="right", va="bottom", transform=fig.transFigure, zorder=20)
        legend = fig.text(0.02, 0.06, "", color="#CCCCCC", fontsize=11,
                          ha="left", va="bottom", transform=fig.transFigure, zorder=20)
        winner_banner = fig.text(0.5, 0.965, "", color="white", fontsize=18, weight="bold",
                                 ha="center", va="top", transform=fig.transFigure, zorder=30)
        winner_banner.set_visible(False)

        # pooled kill-connection artists
        kill_lines = []
        kill_stars = []
        kill_skulls = []
        for _ in range(10):
            line, = ax.plot([], [], color="#FFD700", linewidth=1.5, alpha=0, zorder=7)
            kill_lines.append(line)
            (st,) = ax.plot([], [], marker="*", color="#FFD700", markersize=13,
                            markeredgecolor="black", markeredgewidth=0.5, linestyle="None", alpha=0, zorder=8)
            kill_stars.append(st)
            (sk,) = ax.plot([], [], marker=_SKULL, color="#FF3333", markersize=12,
                            linestyle="None", alpha=0, zorder=8)
            kill_skulls.append(sk)

        ctx = {
            "trail_cols": trail_cols,
            "markers": markers,
            "corpse_marks": corpse_marks,
            "halo": halo,
            "effects": effects,
            "score_text": score_text,
            "round_text": round_text,
            "clock_text": clock_text,
            "legend": legend,
            "kill_lines": kill_lines,
            "kill_stars": kill_stars,
            "kill_skulls": kill_skulls,
            "kill_data": self._kill_windows(),
            "winner_banner": winner_banner,
        }
        return fig, ax, ctx

    # ---- per-frame ----

    def _update_frame(
        self, fig, ax, ctx, tick: float, rnum: int, rng: tuple[int, int],
        px_f, py_f, al_f, dead_info, window_ticks: int,
    ) -> None:
        """Update all artists for one game tick (per-player scalar positions)."""
        trail_cols = ctx["trail_cols"]
        markers = ctx["markers"]
        corpse_marks = ctx["corpse_marks"]
        effects = ctx["effects"]

        for cm in corpse_marks:
            cm.set_alpha(0)
        halo = ctx["halo"]
        if halo is not None:
            halo.set_alpha(0)
        for i, tl in enumerate(self.timelines):
            color = self.colors[i]
            al = bool(al_f[i])
            m = markers[i]
            hi_i = (self.highlight_idx == i)
            if al:
                m.set_data([px_f[i]], [py_f[i]])
                m.set_color(color)
                m.set_alpha(1.0)
                if hi_i and halo is not None:
                    halo.set_data([px_f[i]], [py_f[i]])
                    halo.set_alpha(1.0)
            else:
                m.set_alpha(0)
            # corpse (persists from death tick to round end)
            for (di, dpx, dpy) in dead_info:
                if di == i and not al:
                    corpse_marks[di].set_data([dpx], [dpy])
                    corpse_marks[di].set_alpha(1.0)
            # trail (alive only) — vectorized segment build + pixel conversion
            tc = trail_cols[i]
            if al:
                lo = int(np.searchsorted(tl.ticks, tick - window_ticks, side="left"))
                hi = int(np.searchsorted(tl.ticks, tick, side="right"))
                if hi - lo >= 2:
                    idx = np.arange(lo, hi)
                    wx, wy = tl.xs[idx], tl.ys[idx]
                    dist = np.abs(np.diff(wx)) + np.abs(np.diff(wy))
                    keep = np.nonzero(dist <= _BREAK_DISTANCE)[0]  # drop teleport pairs
                    if keep.size:
                        xs0, ys0 = wx[keep], wy[keep]
                        xs1, ys1 = wx[keep + 1], wy[keep + 1]
                        px0, py0 = self.map.world_to_pixel_array(xs0, ys0)
                        px1, py1 = self.map.world_to_pixel_array(xs1, ys1)
                        psegs = np.stack((np.stack((px0, py0), axis=-1),
                                          np.stack((px1, py1), axis=-1)), axis=1)
                        base = np.asarray(color)
                        n = psegs.shape[0]
                        rgba = np.tile(base, (n, 1))
                        rgba[:, 3] = np.linspace(0.25, 1.0, n)
                        tc.set_segments(psegs)
                        tc.set_color(rgba)
                        lw = (np.linspace(self.config.trail_width_min * 2, self.config.trail_width_max * 2, n) if hi_i
                              else np.linspace(self.config.trail_width_min, self.config.trail_width_max, n))
                        tc.set_linewidths(lw)
                        tc.set_visible(True)
                    else:
                        tc.set_segments([])
                        tc.set_visible(False)
                else:
                    tc.set_segments([])
                    tc.set_visible(False)
            else:
                tc.set_segments([])
                tc.set_visible(False)

        self._update_kills(ctx, tick, ctx["kill_data"])
        effects.update(tick)
        self._update_hud(ctx, tick, rnum)

    def _kill_windows(self):
        """kill index -> (tick, px,py attacker, vpx,vpy victim)."""
        dur = max(int(self.config.kill_duration * self.tick_rate), 1)
        out = []
        for k in self.all_kills:
            ax_, ay_ = self.map.world_to_pixel(k.x, k.y)
            vx_, vy_ = self.map.world_to_pixel(k.victim_x, k.victim_y)
            out.append((k.tick, k.tick + dur, ax_, ay_, vx_, vy_))
        out.sort(key=lambda x: x[0])
        return {
            "starts": np.array([o[0] for o in out], dtype=float),
            "ends": np.array([o[1] for o in out], dtype=float),
            "px": np.array([o[2] for o in out], dtype=float),
            "py": np.array([o[3] for o in out], dtype=float),
            "vpx": np.array([o[4] for o in out], dtype=float),
            "vpy": np.array([o[5] for o in out], dtype=float),
        }

    def _update_kills(self, ctx, tick, kill_data) -> None:
        for ln in ctx["kill_lines"]:
            ln.set_alpha(0)
        for st in ctx["kill_stars"]:
            st.set_alpha(0)
        for sk in ctx["kill_skulls"]:
            sk.set_alpha(0)
        starts, ends = kill_data["starts"], kill_data["ends"]
        if starts.size == 0:
            return
        lo = np.searchsorted(starts, tick, side="right")
        active = np.nonzero(ends[:lo] >= tick)[0]
        n = min(len(active), len(ctx["kill_lines"]))
        for j in range(n):
            i = active[j]
            age = tick - starts[i]
            dur = max(ends[i] - starts[i], 1)
            prog = min(age / dur, 1.0)
            alpha = 1.0 - prog * 0.7
            ctx["kill_lines"][j].set_data([kill_data["px"][i], kill_data["vpx"][i]],
                                          [kill_data["py"][i], kill_data["vpy"][i]])
            ctx["kill_lines"][j].set_alpha(alpha)
            ctx["kill_stars"][j].set_data([kill_data["px"][i]], [kill_data["py"][i]])
            ctx["kill_stars"][j].set_alpha(alpha)
            ctx["kill_skulls"][j].set_data([kill_data["vpx"][i]], [kill_data["vpy"][i]])
            ctx["kill_skulls"][j].set_alpha(alpha)

    def _update_hud(self, ctx, tick, rnum) -> None:
        rnd = next((r for r in self.demo.regular_rounds if r.number == rnum), None)
        if rnd is None:
            return
        meta = self.demo.metadata
        ctx["score_text"].set_text(f"{meta.team_b.name} {rnd.t_score} : {rnd.ct_score} {meta.team_a.name}")
        ctx["round_text"].set_text(f"回合 {rnum}")
        elapsed = (tick - rnd.start_tick) / self.tick_rate
        remain = max(self.config.round_clock_seconds - elapsed, 0)
        mm, ss = divmod(int(remain), 60)
        ctx["clock_text"].set_text(f"{mm}:{ss:02d}")
        lines = []
        for i, tl in enumerate(self.timelines):
            star = "★ " if i == self.highlight_idx else ""
            lines.append(f"{star}{tl.player.name} K{sum(1 for k in tl.kills)}/D{len(tl.deaths)}")
        ctx["legend"].set_text(" | ".join(lines))

    def _index_of(self, steamid_or_name: str) -> int:
        for i, tl in enumerate(self.timelines):
            if tl.player.steamid == steamid_or_name or tl.player.name == steamid_or_name:
                return i
        raise ValueError(
            f"Player {steamid_or_name!r} not in team. "
            f"Available: {[tl.player.name for tl in self.timelines]}"
        )


class _TeamView:
    """Duck-typed PlayerTimeline for EffectManager (utilities + all kills)."""

    def __init__(self, utilities, kills) -> None:
        self.utilities = utilities
        self.kills = kills
        self.shots = []
        self.jumps = []
        self.deaths = []
