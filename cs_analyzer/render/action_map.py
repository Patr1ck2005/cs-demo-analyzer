"""2D action map renderer: player movement trajectories on radar image.

Overlays multiple rounds of a player's movement on the map radar image,
coloring by T/CT side and distinguishing round phases (early/mid/late).
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from cs_analyzer.config import ActionMapConfig
from cs_analyzer.maps import MapResource, load_map
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import Round

logger = logging.getLogger(__name__)

# Round phase boundaries (fraction of round duration)
EARLY_PHASE_END = 1 / 3
MID_PHASE_END = 2 / 3


class ActionMapRenderer:
    """Render a player's movement trajectories across rounds on the map radar."""

    def __init__(
        self,
        config: ActionMapConfig,
        demo: ParsedDemo,
        map_resource: MapResource | None = None,
    ) -> None:
        self.config = config
        self.demo = demo
        if map_resource is None:
            map_name = config.map_name or demo.metadata.map_name
            map_resource = load_map(map_name)
        self.map = map_resource

    def render_player(
        self,
        steamid: str,
        rounds: list[int] | None,
        output_path: str | Path,
        show_kill_markers: bool = True,
    ) -> Path:
        """Render trajectory map for a specific player across selected rounds.

        Args:
            steamid: player steamid
            rounds: 1-indexed round numbers to include (None = all regular rounds)
            output_path: output PNG path
            show_kill_markers: overlay kill/death positions
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        player = self.demo.player(steamid)
        if player is None:
            raise ValueError(f"Player not found: {steamid}")

        all_rounds = self.demo.regular_rounds
        if rounds is None:
            rounds = [r.number for r in all_rounds]
        selected_rounds = [r for r in all_rounds if r.number in rounds]

        fig, ax = plt.subplots(figsize=(10, 10), dpi=self.config.dpi if hasattr(self.config, "dpi") else 150)

        # Background: radar image or blank
        if self.map.image_path is not None:
            img = plt.imread(str(self.map.image_path))
            ax.imshow(img, extent=[0, self.map.image_width, self.map.image_height, 0], origin="upper")
        else:
            ax.set_facecolor("#1a1a1a")
            ax.set_xlim(0, self.map.image_width)
            ax.set_ylim(self.map.image_height, 0)

        # Plot each round's trajectory
        for rnd in selected_rounds:
            self._plot_round_trajectory(ax, steamid, player.team, rnd)

        # Kill/death markers
        if show_kill_markers:
            self._plot_kill_markers(ax, steamid, selected_rounds)

        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(f"{player.name} - {self.map.name} ({len(selected_rounds)} rounds)", color="white", fontsize=14)

        # Legend
        legend_elements = [
            Line2D([0], [0], color=self.config.t_color, linewidth=2, label="T side"),
            Line2D([0], [0], color=self.config.ct_color, linewidth=2, label="CT side"),
            Line2D([0], [0], marker="o", color="w", markerfacecolor="red", markersize=8, label="Death", linestyle="None"),
            Line2D([0], [0], marker="*", color="w", markerfacecolor="yellow", markersize=10, label="Kill", linestyle="None"),
        ]
        ax.legend(handles=legend_elements, loc="upper right", facecolor="#333", edgecolor="white", labelcolor="white")

        fig.patch.set_facecolor("#1a1a1a")
        fig.savefig(output_path, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info("action map -> %s", output_path)
        return output_path

    def _plot_round_trajectory(self, ax, steamid: str, team: str, rnd: Round) -> None:
        """Plot one round's movement trajectory, colored by side, styled by phase."""
        ticks = self.demo.round_ticks(steamid, rnd.number)
        if ticks.empty or "X" not in ticks.columns:
            return

        # Filter to alive ticks
        if "is_alive" in ticks.columns:
            alive = ticks[ticks["is_alive"] == True]  # noqa: E712
            if alive.empty:
                alive = ticks
        else:
            alive = ticks

        px, py = self.map.world_to_pixel_array(alive["X"].values, alive["Y"].values)

        # Determine side for this round (T or CT)
        side = self._player_side_in_round(team, rnd)
        color = self.config.t_color if side == "T" else self.config.ct_color

        if self.config.phase_split:
            self._plot_phased(ax, px, py, color, rnd)
        else:
            ax.plot(px, py, color=color, linewidth=1.5, alpha=0.6)

    def _plot_phased(self, ax, px, py, color: str, rnd: Round) -> None:
        """Plot trajectory with phase-based alpha/width."""
        n = len(px)
        if n < 2:
            return
        early_end = max(int(n * EARLY_PHASE_END), 1)
        mid_end = max(int(n * MID_PHASE_END), 1)

        # Early: thick, high alpha
        ax.plot(px[:early_end], py[:early_end], color=color, linewidth=2.5, alpha=0.8)
        # Mid: medium
        ax.plot(px[early_end:mid_end], py[early_end:mid_end], color=color, linewidth=1.8, alpha=0.6)
        # Late: thin, lower alpha
        ax.plot(px[mid_end:], py[mid_end:], color=color, linewidth=1.2, alpha=0.4, linestyle="--")

    def _plot_kill_markers(self, ax, steamid: str, rounds: list[Round]) -> None:
        """Overlay kill (star) and death (circle) positions for the player."""
        deaths_df = self.demo.events.get("player_death")
        if deaths_df is None or deaths_df.empty:
            return

        for rnd in rounds:
            in_round = (deaths_df["tick"] >= rnd.start_tick) & (deaths_df["tick"] <= rnd.end_tick)
            round_deaths = deaths_df[in_round]

            # Kills (player is attacker)
            kills = round_deaths[round_deaths["attacker_steamid"] == steamid] if "attacker_steamid" in round_deaths.columns else round_deaths.iloc[0:0]
            for _, row in kills.iterrows():
                if "attacker_X" in row and pd_notna(row.get("attacker_X")):
                    kx, ky = self.map.world_to_pixel(float(row["attacker_X"]), float(row["attacker_Y"]))
                    ax.plot(kx, ky, marker="*", color="yellow", markersize=12, markeredgecolor="black", zorder=5)

            # Deaths (player is victim)
            deaths = round_deaths[round_deaths["user_steamid"] == steamid] if "user_steamid" in round_deaths.columns else round_deaths.iloc[0:0]
            for _, row in deaths.iterrows():
                if "user_X" in row and pd_notna(row.get("user_X")):
                    dx, dy = self.map.world_to_pixel(float(row["user_X"]), float(row["user_Y"]))
                    ax.plot(dx, dy, marker="o", color="red", markersize=10, markeredgecolor="black", zorder=5)

    def _player_side_in_round(self, team: str, rnd: Round) -> str:
        """Determine which side (T/CT) the player's team was on in a given round."""
        meta = self.demo.metadata
        team_a = meta.team_a
        team_b = meta.team_b

        if team == team_a.name:
            starts = team_a.starting_side
        elif team == team_b.name:
            starts = team_b.starting_side
        else:
            return "CT"

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


def pd_notna(val) -> bool:
    """Check a value is not NaN/None, pandas-compatible."""
    try:
        import pandas as pd
        return not pd.isna(val)
    except Exception:  # noqa: BLE001
        return val is not None
