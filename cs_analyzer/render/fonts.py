"""matplotlib font setup so HUD text renders CJK player names correctly."""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
from matplotlib import font_manager

logger = logging.getLogger(__name__)

# Candidate Windows font files that include CJK glyphs.
_CJK_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",  # Microsoft YaHei
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",  # SimHei
    "C:/Windows/Fonts/simsun.ttc",  # SimSun
)


def setup_fonts(font_name: str = "Microsoft YaHei") -> str:
    """Register a CJK-capable font and make it the default sans-serif.

    Returns the resolved family name. Raises RuntimeError if no CJK font is
    found, so HUD text never silently degrades to tofu boxes.
    """
    for path in _CJK_FONT_CANDIDATES:
        p = Path(path)
        if p.exists():
            try:
                font_manager.fontManager.addfont(str(p))
            except Exception as exc:  # noqa: BLE001
                logger.debug("failed to register font %s: %s", p, exc)

    family: str | None = None
    try:
        resolved = font_manager.findfont(
            font_manager.FontProperties(family=font_name), fallback_to_default=False
        )
        family = font_manager.FontProperties(fname=resolved).get_name()
    except ValueError:
        for path in _CJK_FONT_CANDIDATES:
            if Path(path).exists():
                family = font_manager.FontProperties(fname=path).get_name()
                break
        if family is not None:
            logger.warning("font '%s' not found; falling back to %s", font_name, family)

    if family is None:
        raise RuntimeError(
            f"No CJK-capable font found (wanted {font_name}). "
            f"Checked: {_CJK_FONT_CANDIDATES}"
        )

    matplotlib.rcParams["font.family"] = "sans-serif"
    sans = list(matplotlib.rcParams["font.sans-serif"])
    if family not in sans:
        sans.insert(0, family)
    matplotlib.rcParams["font.sans-serif"] = sans
    matplotlib.rcParams["axes.unicode_minus"] = False
    logger.info("matplotlib CJK font: %s", family)
    return family
