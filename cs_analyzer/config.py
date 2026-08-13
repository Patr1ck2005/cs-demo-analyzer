"""Configuration models for CsDemoAnalyzer.

Layered settings: defaults < YAML file < environment variables (CSA_ prefix).
All models are pydantic v2 BaseModel; top-level Settings is BaseSettings.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ParserConfig(BaseModel):
    """Layer 1: .dem parsing options."""

    provider: str | None = None  # None = auto-detect
    tick_rate: int = 64
    include_warmup: bool = False
    fields: list[str] = Field(
        default_factory=lambda: [
            "X", "Y", "Z",
            "pitch", "yaw",
            "health", "armor",
            "velocity", "velocity_X", "velocity_Y", "velocity_Z",
            "active_weapon", "is_alive",
            "is_scoped", "is_walking", "is_ducking",
        ]
    )


class AnalysisConfig(BaseModel):
    """Layer 3: which analysis modules to run."""

    enabled_modules: list[str] = Field(default_factory=lambda: ["basic_stats", "ratings"])
    module_options: dict[str, dict] = Field(default_factory=dict)


class RadarChartStyle(BaseModel):
    highlight_color: str = "#FFD700"
    normal_color: str = "#FFFFFF"
    background_color: str = "#1A1A1A"
    radar_size: float = 2.4
    global_opacity: float = 0.5


class RadarChartTiming(BaseModel):
    show_title: float = 3.0
    show_ticks_def: float = 12.0
    show_ticks_max: float = 20.0
    show_ticks_min: float = 29.0
    end_intro: float = 38.0
    end_show: float = 93.0
    entry_times: list[float] | None = None  # None = auto-distribute


class RadarChartAssets(BaseModel):
    player_images_dir: Path = Path("radar_data")
    default_image: Path = Path("radar_data/default.jpg")


class RadarChartConfig(BaseModel):
    title: str = ""
    subtitle: str = ""
    attributes: list[str] = Field(
        default_factory=lambda: [
            "KPR", "Survivals", "ADR", "Headshot%",
            "FirstKillsPerRound", "Rating Pro",
        ]
    )
    attribute_ranges: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "KPR": (0.5, 0.9),
            "Survivals": (0.2, 0.35),
            "ADR": (50.0, 90.0),
            "Headshot%": (30.0, 50.0),
            "FirstKillsPerRound": (0.0, 0.15),
            "RWS": (6.0, 10.0),
            "Rating": (0.7, 1.3),
            "Rating Pro": (0.7, 1.2),
        }
    )
    style: RadarChartStyle = RadarChartStyle()
    timing: RadarChartTiming = RadarChartTiming()
    assets: RadarChartAssets = RadarChartAssets()


class ActionMapConfig(BaseModel):
    """Layer 4: 2D action map options."""

    map_name: str | None = None  # None = infer from demo
    overlap_rounds: int = 10
    phase_split: bool = True  # distinguish early/mid/late round
    t_color: str = "#FF6B6B"  # warm
    ct_color: str = "#4ECDC4"  # cool
    output_format: str = "png"
    dpi: int = 150


class ReplayConfig(BaseModel):
    """2D replay animation options — fine-grained, fully customizable.

    Every visual knob is a field here so recipes (configs/recipes.yaml) can
    override any of them. Renderers read from this config instead of
    hardcoding colors/sizes.
    """

    # ---- canvas / output ----
    fps: int = 30
    dpi: int = 100
    width: int = 1280
    height: int = 720
    bg_color: str = "#1a1a1a"
    font: str = "Microsoft YaHei"

    # ---- playback ----
    speed_full: float = 15.0  # full-match time multiplier
    speed_highlight: float = 1.0
    speed_team: float = 5.0  # 10-player full-record multiplier
    speed_overlay: float = 5.0  # single-player overlay default speed
    team_trail_seconds: float = 1.2  # per-player trail window (output seconds)
    opening_seconds: float = 30.0  # opening window per round (game seconds)
    round_clock_seconds: float = 115.0  # CS2 round timer for HUD countdown
    max_frames: int = 6000  # hard cap on output frames
    overlay_hold_seconds: float = 3.0  # hold the full overlay at the end
    overlay_fade_seconds: float = 1.0  # fade overlay paths out before round/end transitions
    round_end_hold_seconds: float = 1.2  # pause per round-end so the final kill reads
    show_winner_banner: bool = True  # show "T/CT 获胜" banner during the round-end hold

    # ---- team color families (T = warm hues, CT = cool hues) ----
    # Within-family hue spread (not just lightness) so teammates stay
    # distinguishable, while the overall warm/cool contrast reads at a glance.
    t_color: str = "#FFB300"
    ct_color: str = "#29B6F6"
    t_palette: list[str] = ["#FFD54F", "#FFB300", "#FF8F00", "#FF7043", "#F4511E"]
    ct_palette: list[str] = ["#81D4FA", "#29B6F6", "#00BCD4", "#0288D1", "#1565C0"]

    # ---- trail ----
    trail_enabled: bool = True
    trail_seconds: float = 1.5  # trail window in OUTPUT seconds
    trail_segments: int = 6
    trail_width_min: float = 1.2
    trail_width_max: float = 3.5
    trail_alpha_min: float = 0.15
    trail_alpha_max: float = 1.0
    trail_color: str = "#FFFFFF"
    break_distance: float = 300.0  # teleport break threshold (world units)

    # ---- player marker ----
    player_marker_size: float = 9.0
    player_marker_edge: str = "black"
    halo_enabled: bool = True
    halo_size: float = 20.0

    # ---- HUD elements ----
    hud_enabled: bool = True
    hud_show_score: bool = True
    hud_show_round: bool = True
    hud_show_clock: bool = True
    hud_show_feed: bool = True
    hud_show_legend: bool = True

    # ---- per-effect toggles ----
    show_projectiles: bool = True
    show_smoke: bool = True
    show_flash: bool = True
    show_he: bool = True
    show_fire: bool = True
    show_molly: bool = True
    show_kills: bool = True
    show_deaths: bool = True
    show_jumps: bool = True
    show_shots: bool = True

    # ---- effect lifetimes (game-time seconds) ----
    smoke_duration: float = 18.0
    molotov_duration: float = 7.0
    flash_duration: float = 2.0
    he_duration: float = 1.0
    kill_duration: float = 1.2
    death_duration: float = 1.0
    jump_duration: float = 0.4
    shot_frames: int = 1

    # ---- effect colors ----
    smoke_color: str = "#AAAAAA"
    flash_color: str = "#FFFFFF"
    he_color: str = "#FF8800"
    fire_color: str = "#FF6600"
    molly_color: str = "#FF8800"
    projectile_colors: dict[str, str] = {
        "smoke": "#9E9E9E", "flash": "#FFFFFF", "he": "#FF8800",
        "molly": "#FF8800", "fire": "#FF6600",
    }
    shot_color: str = "#FFD700"
    jump_color: str = "#FFD700"
    death_color: str = "#FF3333"
    kill_color: str = "#FFD700"
    victim_color: str = "#FF6666"
    kill_line_color: str = "#FFD700"
    dead_line_color: str = "#7A7A7A"  # 10-player overlay: path of a dead player turns gray

    # ---- effect visuals ----
    smoke_max_radius: float = 120.0
    smoke_grow_seconds: float = 1.0
    smoke_fade_seconds: float = 2.5
    flash_radius: float = 130.0
    he_radius: float = 85.0
    fire_radius: float = 50.0
    nade_projectile_size: float = 4.0
    nade_path_alpha: float = 0.8
    jump_ring_seconds: float = 0.6

    # Estimated grenade flight time (game seconds) used to reconstruct the
    # throw origin. Real grenade flight data is absent from SourceTV demos.
    nade_flight_seconds: dict[str, float] = {
        "smoke": 2.0, "flash": 1.5, "he": 1.5, "molly": 1.5, "fire": 1.5,
    }


class RenderConfig(BaseModel):
    """Layer 4: render options."""

    output_dir: Path = Path("output")
    radar_chart: RadarChartConfig | None = None
    action_map: ActionMapConfig | None = None
    replay: ReplayConfig = ReplayConfig()


class VideoExportConfig(BaseModel):
    background: str | None = None
    music: str | None = None
    use_nvenc: bool = True
    brightness: float = -0.05
    contrast: float = 1.0
    fps: int = 60


class ImageExportConfig(BaseModel):
    format: str = "png"
    dpi: int = 150


class ReportExportConfig(BaseModel):
    format: str = "html"
    template: Path | None = None


class ExportConfig(BaseModel):
    """Layer 5: export options."""

    video: VideoExportConfig = VideoExportConfig()
    image: ImageExportConfig = ImageExportConfig()
    report: ReportExportConfig = ReportExportConfig()


class BatchItem(BaseModel):
    path: Path
    provider: str | None = None


class BatchConfig(BaseModel):
    demos: list[BatchItem] = Field(default_factory=list)
    parallel: int = 4


class Settings(BaseSettings):
    """Top-level settings, loaded from YAML + env."""

    parser: ParserConfig = ParserConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    render: RenderConfig = RenderConfig()
    export: ExportConfig = ExportConfig()
    batch: BatchConfig = BatchConfig()
    cache_dir: Path = Path(".cache")
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="CSA_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def from_yaml(cls, path: str | Path) -> Settings:
        """Load settings from a YAML file, env vars still override."""
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from given YAML, or default search path."""
    if config_path is not None:
        return Settings.from_yaml(config_path)
    for candidate in (Path("configs/default.yaml"), Path("config.yaml")):
        if candidate.exists():
            return Settings.from_yaml(candidate)
    return Settings()
