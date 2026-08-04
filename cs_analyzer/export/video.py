"""Video exporter: ffmpeg compositing (background + foreground + music).

Migrated from ffmpeg_out_put.py. Uses NVENC GPU acceleration when available.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from cs_analyzer.config import VideoExportConfig
from cs_analyzer.export.base import Exporter

logger = logging.getLogger(__name__)


class VideoExporter(Exporter):
    """Composite a foreground Manim video onto a background video with music."""

    def __init__(self, config: VideoExportConfig | None = None) -> None:
        self.config = config or VideoExportConfig()
        self._ffmpeg = self._find_executable("ffmpeg")
        self._ffprobe = self._find_executable("ffprobe")

    @staticmethod
    def _find_executable(name: str) -> str | None:
        """Find an executable, including common Windows locations."""
        import shutil
        path = shutil.which(name)
        if path:
            return path
        # Common alternative locations on Windows (oopz ships ffmpeg without ffprobe)
        candidates = [
            Path("C:/ProgramData/oopz") / f"{name}.exe",
            Path("D:/ProgramData/oopz") / f"{name}.exe",
            Path("C:/ffmpeg/bin") / f"{name}.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return None

    def export(self, input_path: str | Path, output_path: str | Path) -> Path:
        """Overlay foreground video on background + add music.

        Args:
            input_path: foreground video (e.g. Manim .mov output)
            output_path: final composited video path (.mp4)
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not input_path.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        if not self._ffmpeg:
            raise RuntimeError(
                "ffmpeg not found. Install ffmpeg or add it to PATH. "
                "Searched: PATH + C:/ProgramData/oopz + D:/ProgramData/oopz + C:/ffmpeg/bin"
            )

        ffmpeg = self._ffmpeg
        # ffprobe optional - fall back to ffmpeg -i parsing
        ffprobe = self._ffprobe

        if ffprobe:
            duration = self._video_duration(ffprobe, input_path)
            width, height = self._video_resolution(ffprobe, input_path)
        else:
            duration, width, height = self._probe_with_ffmpeg(ffmpeg, input_path)

        # Step 1: overlay foreground on background
        temp_video = output_path.parent / f"{output_path.stem}_temp.mp4"
        self._composite_video(ffmpeg, input_path, temp_video, duration, width, height)

        # Step 2: add music
        if self.config.music and Path(self.config.music).exists():
            self._add_music(ffmpeg, temp_video, output_path, duration)
            temp_video.unlink(missing_ok=True)
        else:
            temp_video.rename(output_path)

        logger.info("exported video -> %s", output_path)
        return output_path

    def _composite_video(
        self,
        ffmpeg: str,
        fg_path: Path,
        out_path: Path,
        duration: float,
        width: int,
        height: int,
    ) -> None:
        """Overlay foreground on looping background, with brightness/contrast adjustment."""
        cmd = [ffmpeg, "-y"]

        if self.config.background and Path(self.config.background).exists():
            cmd += [
                "-stream_loop", "-1",
                "-t", str(duration),
                "-i", self.config.background,
                "-i", str(fg_path),
                "-filter_complex",
                (
                    f"[0:v]scale={width}:{height},"
                    f"eq=brightness={self.config.brightness}:contrast={self.config.contrast}[bg];"
                    f"[bg]format=yuv420p[bgfmt];"
                    f"[bgfmt][1:v]overlay"
                ),
            ]
            if self.config.use_nvenc:
                cmd += ["-c:v", "h264_nvenc"]
        else:
            # No background: just transcode foreground
            cmd += ["-i", str(fg_path), "-filter_complex", f"format=yuv420p"]

        cmd += ["-shortest", str(out_path)]
        self._run(cmd, "video composite")

    def _add_music(self, ffmpeg: str, video_path: Path, out_path: Path, duration: float) -> None:
        """Loop music over the video duration and mux into final output."""
        cmd = [
            ffmpeg, "-y",
            "-i", str(video_path),
            "-stream_loop", "-1",
            "-t", str(duration),
            "-i", self.config.music,
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(out_path),
        ]
        self._run(cmd, "music mux")

    @staticmethod
    def _video_duration(ffprobe: str, video_path: Path) -> float:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
        )
        return float(json.loads(result.stdout)["format"]["duration"])

    @staticmethod
    def _video_resolution(ffprobe: str, video_path: Path) -> tuple[int, int]:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=width,height", "-of", "json", str(video_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
        )
        streams = json.loads(result.stdout)["streams"]
        return int(streams[0]["width"]), int(streams[0]["height"])

    @staticmethod
    def _probe_with_ffmpeg(ffmpeg: str, video_path: Path) -> tuple[float, int, int]:
        """Fallback when ffprobe is unavailable: parse `ffmpeg -i` stderr output.

        Returns (duration_seconds, width, height). Raises on parse failure.
        """
        result = subprocess.run(
            [ffmpeg, "-i", str(video_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        # ffmpeg -i exits non-zero but prints stream info to stderr
        info = result.stderr
        import re

        # Duration: 00:01:32.45, ...
        dur_match = re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", info)
        duration = 0.0
        if dur_match:
            h, m, s = dur_match.groups()
            duration = int(h) * 3600 + int(m) * 60 + float(s)

        # Stream ... Video: ... 1920x1080 ...
        res_match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
        if not res_match:
            raise RuntimeError(f"Could not parse video resolution from ffmpeg -i output:\n{info[:500]}")
        width, height = int(res_match.group(1)), int(res_match.group(2))

        return duration, width, height

    @staticmethod
    def _run(cmd: list[str], label: str) -> None:
        logger.debug("ffmpeg %s: %s", label, " ".join(cmd))
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error("ffmpeg %s failed (rc=%d): %s", label, result.returncode, result.stderr[-500:])
            raise RuntimeError(f"ffmpeg {label} failed: rc={result.returncode}")
