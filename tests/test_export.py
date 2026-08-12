"""Tests for the export layer: VideoExporter ffmpeg probing + ReportExporter."""
from __future__ import annotations

import json
import subprocess

import pytest

from cs_analyzer.analysis.basic_stats import BasicStatsResult, PlayerStats
from cs_analyzer.analysis.ratings import PlayerRatings, RatingsResult
from cs_analyzer.export.report import ReportExporter
from cs_analyzer.export.video import VideoExporter


class _FakeResult:
    def __init__(self, stderr: str, returncode: int = 0) -> None:
        self.stderr = stderr
        self.returncode = returncode


def _ffmpeg_info_stderr() -> str:
    return (
        "ffmpeg version 5.1.2 Copyright (c) 2000-2022 the FFmpeg developers\n"
        "  configuration: --enable-nvenc\n"
        "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'radar.mov':\n"
        "  Duration: 00:01:32.45, start: 0.000000, bitrate: 15221 kb/s\n"
        "  Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), "
        "yuv420p(tv, bt709), 1920x1080 [SAR 1:1 DAR 16:9], 15200 kb/s, 60 fps\n"
    )


def test_probe_with_ffmpeg_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeResult(stderr=_ffmpeg_info_stderr(), returncode=1),
    )
    duration, width, height = VideoExporter._probe_with_ffmpeg("ffmpeg", "radar.mov")
    assert duration == pytest.approx(92.45)
    assert (width, height) == (1920, 1080)


def test_probe_with_ffmpeg_raises_on_missing_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeResult(stderr="no video stream here", returncode=1),
    )
    with pytest.raises(RuntimeError):
        VideoExporter._probe_with_ffmpeg("ffmpeg", "x.mov")


def test_find_executable_returns_none_when_absent(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    assert VideoExporter._find_executable("ffprobe") is None


def test_find_executable_uses_path(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert VideoExporter._find_executable("ffmpeg") == "/usr/bin/ffmpeg"


def _basic() -> BasicStatsResult:
    return BasicStatsResult(
        module="basic_stats", demo_hash="hash123",
        players=[PlayerStats(
            steamid="1", name="Alice", team="Team 3",
            kills=10, deaths=5, damage=500, rounds=10,
            KPR=1.0, ADR=50.0, Survivals=0.5, headshot_pct=40.0, FirstKillsPerRound=0.2,
        )],
    )


def _ratings() -> RatingsResult:
    return RatingsResult(
        module="ratings", demo_hash="hash123",
        players=[PlayerRatings(steamid="1", name="Alice", team="Team 3", RWS=15.0, Rating=1.2, KAST=80.0, Impact=1.0)],
    )


def test_report_json_export(tmp_path) -> None:
    out = tmp_path / "report.json"
    ReportExporter(_basic(), _ratings()).export(None, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["demo_hash"] == "hash123"
    assert data["players"][0]["name"] == "Alice"
    assert data["players"][0]["KPR"] == 1.0
    assert data["players"][0]["RWS"] == 15.0


def test_report_html_export(tmp_path) -> None:
    out = tmp_path / "report.html"
    ReportExporter(_basic(), _ratings()).export(None, out)
    html = out.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "Alice" in html
    assert "Demo Analysis Report" in html


def test_report_rejects_unknown_format(tmp_path) -> None:
    out = tmp_path / "report.txt"
    with pytest.raises(ValueError):
        ReportExporter(_basic(), _ratings()).export(None, out)
