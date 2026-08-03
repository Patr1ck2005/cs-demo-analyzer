"""Radar chart renderer (migrated from cs_radar_chart.py).

Preserves the original Manim animation logic. Changes:
  - Config + player data injected via class attributes (set by RadarChartRenderer)
  - No more hardcoded timing/title/attributes/ranges
  - Data comes from BasicStats + Ratings merge (not CSV)

The scene can still be run via Manim CLI if config + data are pre-loaded,
but the intended entry point is RadarChartRenderer.render().
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from manim import (
    AnimationGroup,
    Circle,
    Create,
    DARKER_GRAY,
    DrawBorderThenFill,
    FadeIn,
    FadeOut,
    GrowFromCenter,
    GrowFromEdge,
    ITALIC,
    LOGO_WHITE,
    PI,
    Polygon,
    Rectangle,
    RIGHT,
    Scene,
    ShrinkToCenter,
    Succession,
    TAU,
    Text,
    Transform,
    Uncreate,
    UP,
    DOWN,
    LEFT,
    VGroup,
    WHITE,
    YELLOW,
    RED,
    BLUE,
    BLACK,
    BOLD,
    Write,
)
import numpy as np

from cs_analyzer.config import RadarChartConfig
from cs_analyzer.render.base import RadarPlayerData
from cs_analyzer.render.image_utils import manim_apply_opacity_to_image, manim_crop_image_to_circle


class PlayerRadarChart(Scene):
    """Manim scene producing the radar chart animation.

    Config and player data are injected via class attributes before render().
    This works around Manim's scene instantiation which doesn't accept args.
    """

    # Class-level injection points (set by RadarChartRenderer)
    _config: ClassVar[RadarChartConfig | None] = None
    _players: ClassVar[list[RadarPlayerData] | None] = None

    def __init__(self) -> None:
        if self._config is None or self._players is None:
            raise RuntimeError(
                "PlayerRadarChart requires config + players. "
                "Use RadarChartRenderer.render() instead of instantiating directly."
            )
        super().__init__()

        cfg = self._config
        self.cfg = cfg
        self.player_data_list = self._players

        self.camera.background_color = DARKER_GRAY
        self.highlight_color = YELLOW
        self.normal_color = WHITE

        self.radar_size = cfg.style.radar_size
        self.global_opacity = cfg.style.global_opacity

        # left-side state
        self.ticks = None
        self.labels = None
        self.marks = None
        self.value_labels = None
        self.radar_chart = None
        self.chart_background_rect = None
        self.shift_vector = None

        self.start_time = None

        self.attributes = list(cfg.attributes)
        self.attribute_ranges = dict(cfg.attribute_ranges)

        # Resolve entry times: explicit config or auto-distribute by player count
        if cfg.timing.entry_times is not None:
            self.entry_times = list(cfg.timing.entry_times)
        else:
            self.entry_times = self._auto_entry_times(len(self.player_data_list), cfg.timing)

        self.time_control = {
            "show_title": cfg.timing.show_title,
            "show_ticks_def": cfg.timing.show_ticks_def,
            "show_ticks_max": cfg.timing.show_ticks_max,
            "show_ticks_min": cfg.timing.show_ticks_min,
            "end_intro": cfg.timing.end_intro,
            "show": self.entry_times,
            "end_show": cfg.timing.end_show,
        }
        self.title_text = cfg.title
        self.music = None  # music is added in ffmpeg post-processing, not Manim

    @staticmethod
    def _auto_entry_times(num_players: int, timing) -> list[float]:
        """Distribute entry times evenly between end_intro and end_show."""
        if num_players == 0:
            return []
        start = timing.end_intro + 4.0
        end = timing.end_show - 2.0
        if num_players == 1:
            return [start]
        spacing = (end - start) / (num_players - 1)
        return [start + spacing * i for i in range(num_players)]

    def construct(self):
        self.start_time = self.renderer.time

        self._show_title()
        self._show_ticks()

        current_time = self.renderer.time - self.start_time
        self.wait(max(self.entry_times[0] - current_time, 0.1))

        players = self.player_data_list
        for i in range(len(self.entry_times)):
            if i >= len(players):
                break
            print(f"下面开始展示选手 {players[i].ID}")
            self._show_player_data(i, players[i], display_time=10)
            if i == len(self.entry_times) - 1:
                self.play(Uncreate(self.radar_chart))
                self.play(
                    AnimationGroup(
                        ShrinkToCenter(self.ticks),
                        ShrinkToCenter(self.chart_background_rect),
                        lag_ratio=0.2,
                    )
                )
        self._show_end()

    def _show_title(self):
        current_time = self.renderer.time - self.start_time
        self.wait(max(self.time_control["show_title"] - current_time, 0.1))

        main_title = Text(self.title_text, font_size=80, color=WHITE)
        subtitle = Text("群友数据图", font_size=60, color=WHITE)

        main_title.to_edge(UP, buff=1.5)
        subtitle.next_to(main_title, DOWN, buff=0.5)

        self.play(Write(main_title, scale=1.5), run_time=3)
        self.wait(1.5)
        self.play(Write(subtitle, shift=DOWN), run_time=1.5)

        current_time = self.renderer.time - self.start_time
        out_time = 1
        self.wait(max(self.time_control["show_ticks_def"] - current_time - out_time, 0.1))

        self.play(FadeOut(main_title), FadeOut(subtitle))

    def _show_ticks(self):
        chart_background_rect = Rectangle(width=7, height=6, color=BLACK, fill_opacity=self.global_opacity)
        ticks = self._draw_ticks()
        ticks.set_z_index(2)
        labels, _, _ = self._draw_labels()
        labels.set_z_index(2)

        ticks_animation = AnimationGroup(
            *[Create(tick) for tick in ticks],
            lag_ratio=0.25,
        )
        label_animation = AnimationGroup(
            *[Write(label) for label in labels][::-1],
            lag_ratio=0.6,
        )
        chart_background_rect.set_z_index(0)

        title = Text("数据维度", font_size=40, color=WHITE).next_to(chart_background_rect, direction=UP)
        self.play(AnimationGroup(GrowFromCenter(chart_background_rect), Write(title), lag_ratio=0.2))
        self.play(AnimationGroup(ticks_animation, label_animation, lag_ratio=1))

        current_time = self.renderer.time - self.start_time
        out_time = 1
        self.wait(max(self.time_control["show_ticks_max"] - current_time - out_time, 0.1))
        self.play(FadeOut(title))

        # max scale
        title = Text("最大刻度", font_size=40, color=WHITE).next_to(chart_background_rect, direction=UP)
        bigger_background_rect = Rectangle(width=9, height=6, color=BLACK, fill_opacity=self.global_opacity)
        bigger_background_rect.set_z_index(0)
        self.play(Write(title))
        self.wait(0.5)
        _, value_labels, _ = self._draw_labels(max_ticks=True)
        value_animation = AnimationGroup(
            Transform(chart_background_rect, bigger_background_rect),
            *[Write(value_label) for value_label in value_labels][::-1],
            lag_ratio=0.1,
        )
        hexagon_vertices = []
        for i, attr in enumerate(self.attributes):
            hexagon_vertices.append(
                self.polar_to_cartesian(i, max(self.attribute_ranges[attr]), *self.attribute_ranges[attr])
                * self.radar_size
            )
        biggest_radar_chart = (
            Polygon(*hexagon_vertices)
            .set_stroke(width=5, color=self.highlight_color)
            .set_fill(self.highlight_color, opacity=0.2)
        )
        biggest_radar_chart.set_z_index(3)
        self.play(GrowFromCenter(biggest_radar_chart))
        self.play(value_animation)

        current_time = self.renderer.time - self.start_time
        out_time = 1
        self.wait(max(self.time_control["show_ticks_min"] - current_time - out_time, 0.1))
        self.play(FadeOut(title), FadeOut(value_labels))

        # min scale
        title = Text("最小刻度", font_size=40, color=WHITE).next_to(chart_background_rect, direction=UP)
        self.play(Write(title))
        self.wait(0.5)
        _, value_labels, _ = self._draw_labels(min_ticks=True)
        value_animation = AnimationGroup(
            *[Write(value_label) for value_label in value_labels][::-1],
            lag_ratio=0.1,
        )
        hexagon_vertices = []
        for i, attr in enumerate(self.attributes):
            lo, hi = self.attribute_ranges[attr]
            scale_val = lo + 0.05 * (hi - lo)
            hexagon_vertices.append(
                self.polar_to_cartesian(i, scale_val, *self.attribute_ranges[attr]) * self.radar_size
            )
        smallest_radar_chart = (
            Polygon(*hexagon_vertices)
            .set_stroke(width=5, color=RED)
            .set_fill(RED, opacity=0.2)
        )
        smallest_radar_chart.set_z_index(3)
        self.play(Transform(biggest_radar_chart, smallest_radar_chart))
        self.play(value_animation)

        current_time = self.renderer.time - self.start_time
        out_time = 1
        self.wait(max(self.time_control["end_intro"] - current_time - out_time, 0.1))
        self.play(
            FadeOut(title),
            FadeOut(biggest_radar_chart),
            FadeOut(chart_background_rect),
            FadeOut(ticks),
            FadeOut(labels),
            FadeOut(value_labels),
        )

    def _show_end(self):
        title = Text("Thinks for Watching", font_size=60, color=WHITE)
        subtitle = Text(datetime.now().strftime("%Y年%m月%d日"), font_size=50, color=WHITE)

        title.to_edge(UP, buff=1.5)
        subtitle.next_to(title, buff=2, direction=DOWN)

        self.play(Write(title, shift=DOWN), run_time=2.5)
        self.play(Write(subtitle), run_time=1.5)
        self.wait(2.5)

        self.play(FadeOut(title), FadeOut(subtitle))

    def _show_player_data(self, index, player_data: RadarPlayerData, display_time):
        if self.chart_background_rect is None:
            self.chart_background_rect = Rectangle(width=7, height=7, color=BLACK, fill_opacity=self.global_opacity)
            self.chart_background_rect.to_edge(LEFT)
            self.chart_background_rect.set_z_index(0)

        left_animation = self._draw_chart(player_data)

        # player icon
        assets_dir = Path(self.cfg.assets.player_images_dir)
        icon_path_png = assets_dir / f"{player_data.ID}.png"
        icon_path_jpg = assets_dir / f"{player_data.ID}.jpg"

        if icon_path_png.exists():
            player_icon = manim_crop_image_to_circle(str(icon_path_png)).scale(2)
        elif icon_path_jpg.exists():
            player_icon = manim_crop_image_to_circle(str(icon_path_jpg)).scale(2)
        else:
            default_img = Path(self.cfg.assets.default_image)
            if default_img.exists():
                player_icon = manim_crop_image_to_circle(str(default_img)).scale(2)
            else:
                player_icon = Circle(radius=1, color=WHITE).set_fill(WHITE, opacity=0.3)

        player_icon.to_edge(RIGHT, buff=1.8)

        circle_border = Circle(
            radius=player_icon.width / 2, color=LOGO_WHITE, stroke_width=8
        ).move_to(player_icon.get_center())

        player_icon_animation_in = AnimationGroup(
            GrowFromEdge(player_icon, edge=RIGHT),
            Create(circle_border),
            lag_ratio=1.2,
        )
        player_icon_animation_out = AnimationGroup(FadeOut(player_icon), FadeOut(circle_border))

        player_id_animation_in, player_id_animation_out = self.show_player_id(player_data, player_icon)

        # team icon
        team_icon_path = assets_dir / f"{player_data.team}.png"
        if team_icon_path.exists():
            team_icon = manim_apply_opacity_to_image(str(team_icon_path), 0.5).scale_to_fit_height(3.2).scale(2)
        else:
            team_icon = Circle(radius=2, color=BLUE).set_opacity(0)
        team_icon.move_to(player_icon)

        team_icon.set_z_index(1)
        player_icon.set_z_index(2)
        circle_border.set_z_index(3)

        team_animation_in = AnimationGroup(GrowFromCenter(team_icon))
        team_animation_out = AnimationGroup(ShrinkToCenter(team_icon), FadeOut(team_icon))

        id_and_icon_animation = AnimationGroup(
            player_id_animation_in, player_icon_animation_in, lag_ratio=0.3
        )
        team_animation = Succession(team_animation_in, team_icon.animate.scale(0.75))

        if index == 0:
            self.play(
                AnimationGroup(
                    id_and_icon_animation,
                    team_animation,
                    AnimationGroup(GrowFromCenter(self.chart_background_rect), left_animation, lag_ratio=0.3),
                    lag_ratio=0.2,
                )
            )
        else:
            self.play(
                AnimationGroup(
                    left_animation, id_and_icon_animation, team_animation, lag_ratio=0.1
                )
            )

        current_time = self.renderer.time - self.start_time
        out_time = 2
        if index < len(self.entry_times) - 1:
            self.wait(max(self.entry_times[index + 1] - current_time - out_time, 0.1))
        else:
            self.wait(max(self.time_control["end_show"] - current_time - out_time, 0.1))

        label_animation = AnimationGroup(
            *[FadeOut(mark) for mark in self.marks],
            *list(
                zip(
                    [FadeOut(label) for label in self.labels],
                    [FadeOut(value_label) for value_label in self.value_labels],
                )
            )[::-1],
            lag_ratio=0.06,
        )
        self.play(
            AnimationGroup(
                label_animation,
                player_icon_animation_out,
                team_animation_out,
                player_id_animation_out,
            ),
            run_time=2,
        )

    def polar_to_cartesian(self, index, value, min_value, max_value):
        angle = -(index % 6 - 1) * (TAU / 6) + PI / 6
        normalized_value = max((value - min_value), 0) / (max_value - min_value)
        radius = normalized_value
        return radius * np.array([np.cos(angle), np.sin(angle), 0])

    def _draw_chart(self, player_data: RadarPlayerData):
        if self.ticks is None:
            ticks = self._draw_ticks()
            self.shift_vector = self.chart_background_rect.get_center() - ticks.get_center()
            ticks.shift(self.shift_vector)

        hexagon_vertices = []
        for i, attr in enumerate(self.attributes):
            value = player_data.attribute_value(attr)
            hexagon_vertices.append(
                self.polar_to_cartesian(i, value, *self.attribute_ranges[attr]) * self.radar_size
            )

        if player_data.is_top:
            color_theme = self.highlight_color
        else:
            color_theme = self.normal_color

        radar_chart = (
            Polygon(*hexagon_vertices)
            .set_stroke(width=5, color=color_theme)
            .set_fill(color_theme, opacity=0.2)
        )
        radar_chart.set_glow(2)

        radar_chart.shift(self.shift_vector)

        labels, value_labels, marks = self._draw_labels(player_data)
        labels.shift(self.shift_vector)
        value_labels.shift(self.shift_vector)
        marks.shift(self.shift_vector)

        radar_chart.set_z_index(0)
        labels.set_z_index(1)
        value_labels.set_z_index(1)

        if self.ticks is None:
            ticks_animation = AnimationGroup(
                *[GrowFromCenter(tick) for tick in ticks], lag_ratio=0.15
            )
        if self.radar_chart is None:
            radar_chart_animation = DrawBorderThenFill(radar_chart)
            self.radar_chart = radar_chart
        else:
            radar_chart_animation = Transform(self.radar_chart, radar_chart)

        label_animation = AnimationGroup(
            AnimationGroup(
                *list(
                    zip(
                        [FadeIn(label) for label in labels],
                        [Write(value_label) for value_label in value_labels],
                    )
                ),
                lag_ratio=0.1,
            ),
            *[Write(mark) for mark in marks],
            lag_ratio=0.5,
        )
        if self.ticks is None:
            left_animation = AnimationGroup(
                ticks_animation, radar_chart_animation, label_animation, lag_ratio=0.5
            )
        else:
            left_animation = AnimationGroup(
                radar_chart_animation, label_animation, lag_ratio=0.3
            )
        if self.ticks is None:
            self.ticks = ticks
        self.labels = labels
        self.value_labels = value_labels
        self.marks = marks
        return left_animation

    def _draw_ticks(self):
        ticks = []
        num_scales = 7
        for scale_index in range(1, num_scales):
            scale_value = scale_index / (num_scales - 1)
            hexagon_vertices = []
            for i, attr in enumerate(self.attributes):
                min_value, max_value = self.attribute_ranges[attr]
                scale_val = min_value + scale_value * (max_value - min_value)
                hexagon_vertices.append(
                    self.polar_to_cartesian(i, scale_val, min_value, max_value) * self.radar_size
                )
            hexagon = Polygon(*hexagon_vertices)
            if scale_index == num_scales - 1:
                hexagon.set_stroke(width=5, color=BLUE)
                hexagon.set_glow(2)
            else:
                hexagon.set_stroke(width=2, color=WHITE)
            ticks.append(hexagon)
        return VGroup(*ticks)

    def _draw_labels(self, player_data: RadarPlayerData | None = None, max_ticks=False, min_ticks=False):
        labels = VGroup()
        value_labels = VGroup()
        marks = VGroup()
        for i, attr in enumerate(self.attributes):
            pos = (
                self.polar_to_cartesian(i, max(self.attribute_ranges[attr]), *self.attribute_ranges[attr])
                * self.radar_size
            )
            original_pos = pos.copy()
            if i in (5, 0, 1):
                pos[1] += 0.3
            if i in (2, 3, 4):
                pos[1] -= 0.3
            if i in (1, 2):
                pos[0] += 0.5
            if i in (4, 5):
                pos[0] -= 0.5

            display_name = "FirstKill" if attr == "FirstKillsPerRound" else attr
            label = Text(display_name).scale(0.5).move_to(pos)

            if player_data is not None:
                rank = player_data.attribute_rank(attr)
                paras = (
                    {"font": "Bodoni MT Black", "slant": ITALIC} if rank == 1 else {}
                )
                raw = player_data.attribute_value(attr)
                if raw < 1:
                    value_label = Text(
                        str(float(np.format_float_scientific(raw, 1, trim="k"))), **paras
                    ).scale(0.8)
                else:
                    value_label = Text(
                        str(float(np.format_float_scientific(raw, 2, trim="k"))), **paras
                    ).scale(0.8)
                value_label.next_to(label, RIGHT)
                if i == 4 or i == 5:
                    value_label.next_to(label, DOWN)

                if rank == 1:
                    label.set_stroke(color=self.highlight_color)
                    label.scale(1.2)
                    value_label.set_stroke(color=self.highlight_color, width=1)
                    value_label.scale(1.4)
                    best_label = Text(
                        "Best",
                        font="Bodoni MT Black",
                        slant=ITALIC,
                        stroke_color=self.highlight_color,
                        stroke_width=3,
                        stroke_opacity=0.5,
                    ).scale(1)
                    best_label.move_to(original_pos)
                    best_label.next_to(value_label, UP)
                    if i == 4 or i == 5:
                        best_label.next_to(label, UP)
                    marks.add(best_label)
                value_labels.add(value_label)
            elif max_ticks:
                value_label = Text(str(np.round(max(self.attribute_ranges[attr]), 1))).scale(0.8)
                value_labels.add(value_label)
            elif min_ticks:
                value_label = Text(str(np.round(min(self.attribute_ranges[attr]), 1))).scale(0.8)
                value_labels.add(value_label)
            labels.add(label)

        for i, value_label in enumerate(value_labels):
            value_label.next_to(labels[i], RIGHT)
            if i == 4 or i == 5:
                value_label.next_to(labels[i], DOWN)
        return labels, value_labels, marks

    def show_player_id(self, player_data: RadarPlayerData, player_icon):
        player_id = player_data.ID

        if player_data.is_top:
            color_theme = self.highlight_color
        else:
            color_theme = BLUE
        player_id_text_stroke = Text(
            player_id,
            font_size=72,
            font="Microsoft YaHei",
            weight=BOLD,
            slant=ITALIC,
            stroke_width=3,
            stroke_color=color_theme,
            fill_opacity=0,
        ).scale(1.4)
        player_id_text = Text(
            player_id,
            font_size=72,
            font="Microsoft YaHei",
            weight=BOLD,
            slant=ITALIC,
            color=WHITE,
        ).scale(1.2)

        player_id_text.set_z_index(3)
        player_id_text_stroke.set_z_index(2)

        player_id_text.next_to(player_icon, UP, buff=1.0).shift(LEFT * 0.8)
        player_id_text_stroke.next_to(player_icon, UP, buff=0.8)
        player_id_text_stroke.shift(RIGHT * 0.5)

        animation_in = AnimationGroup(
            Write(player_id_text), Write(player_id_text_stroke, run_time=2), lag_ratio=1.2
        )
        animation_out = AnimationGroup(
            FadeOut(player_id_text), FadeOut(player_id_text_stroke), lag_ratio=0.3
        )
        return animation_in, animation_out


class RadarChartRenderer:
    """Orchestrates PlayerRadarChart rendering with config + data injection."""

    def __init__(self, config: RadarChartConfig, players: list[RadarPlayerData]) -> None:
        self.config = config
        self.players = players

    def render(
        self,
        output_path: str | Path,
        quality: str = "high_quality",
        transparent: bool = True,
        format: str = "mov",
    ) -> Path:
        """Render the radar chart to a video file.

        Args:
            output_path: target file path (.mov or .mp4)
            quality: manim quality preset ("low_quality", "medium_quality", "high_quality", "production_quality")
            transparent: render with transparent background (for overlay compositing)
            format: output container ("mov" or "mp4")
        """
        from manim import config as manim_config

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Inject config + data into the scene class
        PlayerRadarChart._config = self.config
        PlayerRadarChart._players = self.players

        # Configure manim
        media_dir = output_path.parent / "media"
        manim_config.media_dir = str(media_dir)
        manim_config.output_file = output_path.stem
        manim_config.format = format
        manim_config.quality = quality
        manim_config.transparent = transparent

        scene = PlayerRadarChart()
        scene.render()

        # Manim writes to media_dir/<quality>/<name>.<ext>; find the actual output
        produced = self._find_produced_video(media_dir, output_path.stem, format)
        if produced is None:
            raise RuntimeError(f"Manim did not produce expected output for {output_path.stem}")
        return produced

    @staticmethod
    def _find_produced_video(media_dir: Path, name: str, fmt: str) -> Path | None:
        """Locate the rendered video file in manim's media directory."""
        for ext in (f".{fmt}", ".mp4", ".mov"):
            candidates = list(media_dir.rglob(f"{name}{ext}"))
            if candidates:
                return candidates[0]
        return None
