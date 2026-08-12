"""Shared ffmpeg/ffprobe executable discovery."""
from __future__ import annotations

import shutil
from pathlib import Path

# Common Windows locations (oopz ships ffmpeg without ffprobe).
_FALLBACK_DIRS = (
    Path("C:/ProgramData/oopz"),
    Path("D:/ProgramData/oopz"),
    Path("C:/ffmpeg/bin"),
)


def find_executable(name: str) -> str | None:
    """Locate an executable on PATH or common Windows install dirs."""
    path = shutil.which(name)
    if path:
        return path
    for d in _FALLBACK_DIRS:
        candidate = d / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    return None


def find_ffmpeg() -> str:
    """Return an ffmpeg path or raise."""
    exe = find_executable("ffmpeg")
    if not exe:
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg or add it to PATH. "
            "Searched: PATH + C:/ProgramData/oopz + D:/ProgramData/oopz + C:/ffmpeg/bin"
        )
    return exe
