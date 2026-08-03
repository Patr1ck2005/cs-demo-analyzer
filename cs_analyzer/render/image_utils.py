"""Image utilities for Manim renderers.

Migrated from utils/image_pre.py to live inside the package. Provides
circular crop and opacity adjustment for player/team icons.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw


def crop_image_to_circle(image_path: str, output_path: str) -> None:
    """Crop a rectangular image to a circle (alpha mask), save as PNG."""
    img = Image.open(image_path).convert("RGBA")
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0) + img.size, fill=255)
    img.putalpha(mask)
    img.save(output_path, format="PNG")


def manim_crop_image_to_circle(image_path: str):
    """Crop image to circle and return a Manim ImageMobject."""
    from manim import ImageMobject

    image_dir = os.path.dirname(image_path)
    image_name = Path(image_path).stem
    temp_dir = os.path.join(image_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{image_name}_cropped_image.png")

    img = Image.open(image_path).convert("RGBA")
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0) + img.size, fill=255)
    img.putalpha(mask)
    img.save(temp_path, format="PNG")
    return ImageMobject(temp_path)


def manim_apply_opacity_to_image(image_path: str, opacity: float):
    """Return a Manim ImageMobject with overall opacity multiplied by `opacity`."""
    from manim import ImageMobject

    image_dir = os.path.dirname(image_path)
    image_name = Path(image_path).stem
    temp_dir = os.path.join(image_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{image_name}_with_opacity.png")

    img = Image.open(image_path).convert("RGBA")
    alpha = img.split()[3]
    alpha = alpha.point(lambda p: p * opacity)
    img.putalpha(alpha)
    img.save(temp_path, format="PNG")
    return ImageMobject(temp_path)
