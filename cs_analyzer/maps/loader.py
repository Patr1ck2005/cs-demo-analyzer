"""Map resource loader: radar image + coordinate transformation."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAPS_DATA_DIR = Path(__file__).parent / "data"


class MapBounds(BaseModel):
    """World coordinate bounds for a map's playable area."""

    min_x: float
    max_x: float
    min_y: float
    max_y: float


class MapResource:
    """A loaded map: radar image path + coordinate bounds + transformation."""

    def __init__(self, name: str, bounds: MapBounds, image_path: Path | None, image_width: int, image_height: int) -> None:
        self.name = name
        self.bounds = bounds
        self.image_path = image_path
        self.image_width = image_width
        self.image_height = image_height

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """Transform world (X, Y) to radar image pixel (px, py).

        Y-axis is flipped: world Y increases north, image Y increases south.
        """
        b = self.bounds
        px = (x - b.min_x) / (b.max_x - b.min_x) * self.image_width
        py = (1 - (y - b.min_y) / (b.max_y - b.min_y)) * self.image_height
        return px, py

    def world_to_pixel_array(self, xs, ys):
        """Vectorized world-to-pixel for arrays (returns numpy arrays)."""
        import numpy as np

        xs = np.asarray(xs, dtype=float)
        ys = np.asarray(ys, dtype=float)
        b = self.bounds
        px = (xs - b.min_x) / (b.max_x - b.min_x) * self.image_width
        py = (1 - (ys - b.min_y) / (b.max_y - b.min_y)) * self.image_height
        return px, py


def load_map(map_name: str, maps_dir: Path | None = None) -> MapResource:
    """Load a map's resources from YAML + check for radar image.

    Args:
        map_name: e.g. "de_mirage"
        maps_dir: directory containing {map_name}.yaml and optionally {map_name}.png.
                  Defaults to cs_analyzer/maps/data/.
    """
    maps_dir = maps_dir or MAPS_DATA_DIR
    yaml_path = maps_dir / f"{map_name}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"No map data for '{map_name}'. Expected {yaml_path}. "
            f"Add map YAML to cs_analyzer/maps/data/ or pass maps_dir."
        )

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    bounds = MapBounds(**data["bounds"])
    image_width = int(data["image_width"])
    image_height = int(data["image_height"])

    image_path = maps_dir / f"{map_name}.png"
    if not image_path.exists():
        logger.warning("radar image not found: %s (trajectories will render on blank background)", image_path)
        image_path = None

    return MapResource(
        name=map_name,
        bounds=bounds,
        image_path=image_path,
        image_width=image_width,
        image_height=image_height,
    )


def derive_bounds_from_ticks(ticks) -> MapBounds:
    """Estimate playable-area bounds from tick position data.

    Uses the 1st/99th percentiles of alive, finite X/Y with 5% padding, so a
    handful of outlier coordinates (glitches, teleports) don't blow out the map.
    """
    import numpy as np
    import pandas as pd

    if ticks is None or ticks.empty or "X" not in ticks.columns:
        return MapBounds(min_x=-2000.0, max_x=2000.0, min_y=-2000.0, max_y=2000.0)

    df = ticks[["X", "Y"]]
    if "is_alive" in ticks.columns:
        alive = ticks["is_alive"].fillna(False).astype(bool)
        df = df[alive]
    df = df.replace([float("inf"), float("-inf")], float("nan")).dropna()
    if df.empty:
        return MapBounds(min_x=-2000.0, max_x=2000.0, min_y=-2000.0, max_y=2000.0)

    xs, ys = df["X"].values, df["Y"].values
    min_x, max_x = np.percentile(xs, [1, 99])
    min_y, max_y = np.percentile(ys, [1, 99])
    pad_x = (max_x - min_x) * 0.05
    pad_y = (max_y - min_y) * 0.05
    return MapBounds(
        min_x=float(min_x - pad_x),
        max_x=float(max_x + pad_x),
        min_y=float(min_y - pad_y),
        max_y=float(max_y + pad_y),
    )


def load_map_or_fallback(map_name: str, ticks=None, maps_dir: Path | None = None) -> MapResource:
    """Load a map resource, deriving bounds from tick data when no YAML exists.

    Falls back to a dark blank canvas with a square size chosen to match the
    derived bounds' aspect ratio, so world->pixel transforms stay undistorted.
    """
    try:
        return load_map(map_name, maps_dir=maps_dir)
    except FileNotFoundError:
        bounds = derive_bounds_from_ticks(ticks)
        span_x = bounds.max_x - bounds.min_x
        span_y = bounds.max_y - bounds.min_y
        size = 1200
        if span_x > 0 and span_y > 0:
            width, height = size, int(size * span_y / span_x)
        else:
            width = height = size
        logger.warning(
            "no map data for '%s'; using tick-derived bounds (%s)", map_name, bounds
        )
        return MapResource(
            name=map_name,
            bounds=bounds,
            image_path=None,
            image_width=width,
            image_height=height,
        )
