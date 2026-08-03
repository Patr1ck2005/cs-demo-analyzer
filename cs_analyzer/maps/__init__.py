"""Map resources: radar images and world-to-pixel coordinate mappings.

Each map needs:
  - A radar image (top-down PNG, user-provided from CS2 game files)
  - A YAML file with world coordinate bounds + image dimensions

The transformation is a linear scale with Y-axis flip:
  pixel_x = (world_x - min_x) / (max_x - min_x) * image_width
  pixel_y = (1 - (world_y - min_y) / (max_y - min_y)) * image_height
"""
from cs_analyzer.maps.loader import MapResource, load_map

__all__ = ["MapResource", "load_map"]
