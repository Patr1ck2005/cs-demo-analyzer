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

        b = self.bounds
        px = (xs - b.min_x) / (b.max_x - b.min_x) * self.image_width
        py = (1 - (ys - b.min_y) / (b.max_y - b.min_y)) * self.image_height
        return np.asarray(px), np.asarray(py)


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
