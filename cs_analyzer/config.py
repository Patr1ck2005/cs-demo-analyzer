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


class Settings(BaseSettings):
    """Top-level settings, loaded from YAML + env."""

    parser: ParserConfig = ParserConfig()
    analysis: AnalysisConfig = AnalysisConfig()
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
