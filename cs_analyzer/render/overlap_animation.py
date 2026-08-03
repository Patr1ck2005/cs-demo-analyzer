"""T/CT overlap animation: player's T-side and CT-side trajectories animated over time.

Uses matplotlib FuncAnimation to progressively draw each round's movement,
first T-side rounds then CT-side, both visible at the end.
Outputs MP4 (ffmpeg) or GIF (pillow).
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.lines import Line2D

from cs_analyzer.config import OverlapAnimationConfig
from cs_analyzer.maps import MapResource, load_map
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import Round

logger = logging.getLogger(__name__)

# Samples per round trajectory (downsample for smooth animation)
SAMPLES_PER_ROUND = 60


class OverlapAnimationRenderer:
    """Animate a player's T-side and CT-side trajectories on the map radar."""

    def __init__(
        self,
        config: OverlapAnimationConfig,
        demo: ParsedDemo,
        map_resource: MapResource | None = None,
    ) -> None:
        self.config = config
        self.demo = demo
        if map_resource is None:
            map_name = demo.metadata.map_name
            map_resource = load_map(map_name)
        self.map = map_resource

    def render_player(
        self,
        steamid: str,
        output_path: str | Path,
    ) -> Path:
        """Render T/CT overlap animation for a player.

        Args:
            steamid: player steamid
            output_path: output file (.mp4 or .gif)
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        player = self.demo.player(steamid)
        if player is None:
            raise ValueError(f"Player not found: {steamid}")

        # Split rounds by side
        t_rounds, ct_rounds = self._split_rounds_by_side(player.team)
        t_traces = [self._round_trace(r, steamid) for r in t_rounds]
        ct_traces = [self._round_trace(r, steamid) for r in ct_rounds]

        # Filter empty traces
        t_traces = [t for t in t_traces if t is not None]
        ct_traces = [t for t in ct_traces if t is not None]

        if not t_traces and not ct_traces:
            raise ValueError(f"No trajectory data for player {player.name}")

        # Build frame sequence: T traces first, then CT traces
        all_traces = [(t, "T") for t in t_traces] + [(t, "CT") for t in ct_traces]
        total_frames = len(all_traces) * SAMPLES_PER_ROUND

        fig, ax = plt.subplots(figsize=(10, 10))

        # Background
        if self.map.image_path is not None:
            img = plt.imread(str(self.map.image_path))
            ax.imshow(img, extent=[0, self.map.image_width, self.map.image_height, 0], origin="upper")
        else:
            ax.set_facecolor("#1a1a1a")
            ax.set_xlim(0, self.map.image_width)
            ax.set_ylim(self.map.image_height, 0)

        # Line objects for T and CT
        t_line, = ax.plot([], [], color=self._t_color(), linewidth=2.0, alpha=0.7, label="T side")
        ct_line, = ax.plot([], [], color=self._ct_color(), linewidth=2.0, alpha=0.7, label="CT side")

        # Current-position markers
        t_marker, = ax.plot([], [], "o", color=self._t_color(), markersize=8)
        ct_marker, = ax.plot([], [], "o", color=self._ct_color(), markersize=8)

        ax.set_aspect("equal")
        ax.axis("off")
        title = ax.set_title(f"{player.name} - T/CT Movement", color="white", fontsize=14)
        ax.legend(loc="upper right", facecolor="#333", edgecolor="white", labelcolor="white")
        fig.patch.set_facecolor("#1a1a1a")

        # Accumulated points - rebuilt each frame to avoid extend-delta bugs
        def init():
            t_line.set_data([], [])
            ct_line.set_data([], [])
            t_marker.set_data([], [])
            ct_marker.set_data([], [])
            return t_line, ct_line, t_marker, ct_marker

        def update(frame: int):
            t_visible_x: list[float] = []
            t_visible_y: list[float] = []
            ct_visible_x: list[float] = []
            ct_visible_y: list[float] = []
            current_marker = None
            current_side = None

            for i, (trace, side) in enumerate(all_traces):
                full_frames = i * SAMPLES_PER_ROUND
                if frame < full_frames:
                    continue  # not started yet
                elapsed = frame - full_frames
                px, py = trace
                reveal = int((elapsed + 1) / SAMPLES_PER_ROUND * len(px))
                reveal = min(reveal, len(px))

                if side == "T":
                    t_visible_x.extend(px[:reveal])
                    t_visible_y.extend(py[:reveal])
                else:
                    ct_visible_x.extend(px[:reveal])
                    ct_visible_y.extend(py[:reveal])

                # Track current position (last revealed point of the currently animating trace)
                if full_frames <= frame < full_frames + SAMPLES_PER_ROUND:
                    current_marker = (px[reveal - 1], py[reveal - 1])
                    current_side = side

            t_line.set_data(t_visible_x, t_visible_y)
            ct_line.set_data(ct_visible_x, ct_visible_y)

            if current_marker is not None:
                if current_side == "T":
                    t_marker.set_data([current_marker[0]], [current_marker[1]])
                    ct_marker.set_data([], [])
                    t_idx = frame // SAMPLES_PER_ROUND + 1
                    title.set_text(f"{player.name} - T side (round {t_idx}/{len(t_traces)})")
                else:
                    ct_marker.set_data([current_marker[0]], [current_marker[1]])
                    t_marker.set_data([], [])
                    ct_idx = (frame // SAMPLES_PER_ROUND) - len(t_traces) + 1
                    title.set_text(f"{player.name} - CT side (round {ct_idx}/{len(ct_traces)})")
            else:
                t_marker.set_data([], [])
                ct_marker.set_data([], [])

            return t_line, ct_line, t_marker, ct_marker

        anim = FuncAnimation(
            fig, update, init_func=init, frames=total_frames,
            interval=1000 / self.config.fps, blit=False, repeat=False,
        )

        # Save
        fmt = output_path.suffix.lower()
        if fmt == ".mp4":
            anim.save(str(output_path), writer="ffmpeg", fps=self.config.fps, dpi=100)
        elif fmt == ".gif":
            anim.save(str(output_path), writer="pillow", fps=self.config.fps)
        else:
            raise ValueError(f"Unsupported animation format: {fmt}. Use .mp4 or .gif")

        plt.close(fig)
        logger.info("overlap animation -> %s", output_path)
        return output_path

    def _split_rounds_by_side(self, team: str) -> tuple[list[Round], list[Round]]:
        """Split regular rounds into T-side and CT-side for the player's team."""
        meta = self.demo.metadata
        if team == meta.team_a.name:
            starts = meta.team_a.starting_side
        elif team == meta.team_b.name:
            starts = meta.team_b.starting_side
        else:
            return [], []

        t_rounds: list[Round] = []
        ct_rounds: list[Round] = []
        for rnd in self.demo.regular_rounds:
            side = self._side_for_round(rnd, starts)
            if side == "T":
                t_rounds.append(rnd)
            else:
                ct_rounds.append(rnd)
        return t_rounds, ct_rounds

    @staticmethod
    def _side_for_round(rnd: Round, starts: str) -> str:
        other = "T" if starts == "CT" else "CT"
        reg_num = rnd.number
        if rnd.is_overtime:
            ot_num = reg_num - 12
            swap = (ot_num - 1) // 6
        else:
            swap = 0 if reg_num <= 12 else 1
        if swap % 2 == 0:
            return starts
        return other

    def _round_trace(self, rnd: Round, steamid: str) -> tuple[np.ndarray, np.ndarray] | None:
        """Get downsampled pixel coordinates for a player in a round."""
        ticks = self.demo.round_ticks(steamid, rnd.number)
        if ticks.empty or "X" not in ticks.columns:
            return None
        if "is_alive" in ticks.columns:
            alive = ticks[ticks["is_alive"] == True]  # noqa: E712
            if alive.empty:
                alive = ticks
        else:
            alive = ticks
        if len(alive) < 2:
            return None

        px, py = self.map.world_to_pixel_array(alive["X"].values, alive["Y"].values)
        # Downsample to SAMPLES_PER_ROUND points
        if len(px) > SAMPLES_PER_ROUND:
            idx = np.linspace(0, len(px) - 1, SAMPLES_PER_ROUND, dtype=int)
            px = px[idx]
            py = py[idx]
        return px, py

    def _t_color(self) -> str:
        return "#FF6B6B"

    def _ct_color(self) -> str:
        return "#4ECDC4"
