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


class OverlapAnimationConfig(BaseModel):
    """Layer 4: T/CT overlap animation options."""

    duration: float = 15.0
    fps: int = 30
    output_format: str = "mp4"


class RenderConfig(BaseModel):
    """Layer 4: render options."""

    output_dir: Path = Path("output")
    radar_chart: RadarChartConfig | None = None
    action_map: ActionMapConfig | None = None
    overlap_animation: OverlapAnimationConfig | None = None


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
