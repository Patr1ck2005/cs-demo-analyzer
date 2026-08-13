"""Parse-coverage scanning: how completely each demo parses and can replay.

Produces per-demo, per-player coverage facts that drive:
  - the coverage report (LTG-3, `csa coverage` -> output/coverage/coverage.html)
  - the web app's "can this player be replayed?" checks (LTG-2)

The single-source signal for replayability is whether demoparser2 tracked the
player's per-tick position (X/Y non-NaN). Some SourceTV demos omit entity
tracking for certain players -> those are "Team 0" / non-replayable.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cs_analyzer.cache import DemoCache
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.parser.manager import ParseManager

logger = logging.getLogger(__name__)

# CS2 team numbers: 2 = T, 3 = CT. Anything else (0/1, or the string forms)
# means the player was never assigned a real side.
_TEAM_LABEL = {"Team 2": "T", "Team 3": "CT"}


@dataclass
class PlayerCoverage:
    steamid: str
    name: str
    team: str
    has_position: bool  # per-tick X/Y present (any non-NaN)
    position_ratio: float  # 0..1 fraction of non-NaN X samples
    replayable: bool  # can build a single-player replay
    team_zero: bool  # not assigned to Team 2 / Team 3

    @property
    def team_label(self) -> str:
        return _TEAM_LABEL.get(self.team, "Team 0")


@dataclass
class DemoCoverage:
    path: str
    demo_hash: str
    map_name: str
    provider: str
    num_rounds: int
    regular_rounds: int
    t_score: int
    ct_score: int
    players: list[PlayerCoverage] = field(default_factory=list)
    event_tables: list[str] = field(default_factory=list)
    cache_hit: bool = False
    parse_seconds: float = 0.0
    status: str = "ok"  # ok | error
    error: str | None = None

    @property
    def team_zero_players(self) -> list[PlayerCoverage]:
        return [p for p in self.players if p.team_zero]

    @property
    def replayable_players(self) -> list[PlayerCoverage]:
        return [p for p in self.players if p.replayable]


def _player_position_stats(demo: ParsedDemo) -> dict[str, tuple[bool, float]]:
    """steamid -> (has_position, non_nan_ratio) from the tick table."""
    out: dict[str, tuple[bool, float]] = {}
    ticks = demo.ticks
    if ticks is None or ticks.empty or "X" not in ticks.columns:
        return {p.steamid: (False, 0.0) for p in demo.players}
    for p in demo.players:
        sub = ticks[ticks["steamid"] == p.steamid]
        if sub.empty:
            out[p.steamid] = (False, 0.0)
            continue
        x = sub["X"].to_numpy(dtype=float)
        n = x.size
        ok = int(np.isfinite(x).sum())
        out[p.steamid] = (ok > 0, ok / n if n else 0.0)
    return out


def _score(demo: ParsedDemo) -> tuple[int, int]:
    reg = demo.regular_rounds
    if not reg:
        return 0, 0
    last = reg[-1]
    return last.t_score, last.ct_score


def scan_demo(
    path: str | Path,
    cache: DemoCache | None = None,
    use_cache: bool = True,
) -> DemoCoverage:
    """Scan one .dem file into a DemoCoverage (parse or cache-hit)."""
    path = Path(path)
    cache = cache or DemoCache(Path(".cache"))
    manager = ParseManager(cache=cache)

    # Cache-hit detection needs the hash before parsing; ParseManager re-hashes
    # internally, so a one-time coverage run pays SHA256 twice — acceptable.
    try:
        demo_hash = DemoCache.hash_demo(path)
        cache_hit = use_cache and cache.exists(demo_hash)
    except Exception as exc:  # noqa: BLE001
        return DemoCoverage(
            path=str(path), demo_hash="", map_name="?", provider="?",
            num_rounds=0, regular_rounds=0, t_score=0, ct_score=0,
            status="error", error=str(exc),
        )

    t0 = time.time()
    try:
        demo = manager.parse(path, use_cache=use_cache)
        parse_seconds = time.time() - t0
    except Exception as exc:  # noqa: BLE001
        logger.exception("coverage scan failed for %s", path)
        return DemoCoverage(
            path=str(path), demo_hash=demo_hash, map_name="?", provider="?",
            num_rounds=0, regular_rounds=0, t_score=0, ct_score=0,
            cache_hit=cache_hit, status="error", error=str(exc),
        )

    pos = _player_position_stats(demo)
    players = [
        PlayerCoverage(
            steamid=p.steamid,
            name=p.name,
            team=p.team,
            has_position=pos.get(p.steamid, (False, 0.0))[0],
            position_ratio=pos.get(p.steamid, (False, 0.0))[1],
            replayable=pos.get(p.steamid, (False, 0.0))[0],
            team_zero=p.team not in ("Team 2", "Team 3"),
        )
        for p in demo.players
    ]
    t_score, ct_score = _score(demo)
    events = [t for t, df in demo.events.items() if df is not None and not df.empty]
    return DemoCoverage(
        path=str(path),
        demo_hash=demo.metadata.demo_hash,
        map_name=demo.metadata.map_name,
        provider=demo.metadata.provider.value,
        num_rounds=len(demo.rounds),
        regular_rounds=len(demo.regular_rounds),
        t_score=t_score,
        ct_score=ct_score,
        players=players,
        event_tables=sorted(events),
        cache_hit=cache_hit,
        parse_seconds=parse_seconds,
    )


def scan_demos(
    paths: list[str | Path],
    cache: DemoCache | None = None,
    use_cache: bool = True,
) -> list[DemoCoverage]:
    return [scan_demo(p, cache=cache, use_cache=use_cache) for p in paths]


# ---- HTML report ----

_TEMPLATE_DIR = Path(__file__).parent / "web" / "templates"

# Findings from the Phase 1b investigation (probe_team0.py) into players with
# no position data. Kept here so the report is self-contained.
DEFAULT_CONCLUSIONS: list[str] = [
    "demoparser2 库层限制：WMPVP SourceTV 广播中，个别玩家的 pawn 实体完全无法解析——"
    "ticks 表 X/Y/Z/health/team_num 全 NaN、is_alive 恒 False，且所有事件（spawn/death/fire/"
    "hurt/jump）的位置字段同样全 NaN。该玩家事件计数层面完全活跃（每回合 spawn、击杀/死亡/"
    "伤害/射击齐全），但整个 demo 无任何位置数据。",
    "不可修复/不可绕过：经 demoparser2 直接解析确认（parse_player_info 为空、parse_ticks 对该"
    "玩家全部 X NaN），这是库/SourceTV 数据层限制，非本解析层 bug；事件亦无位置，无法重建稀疏轨迹。",
    "玩家特定性：同一 steamid 在不同 demo 表现不同（如 '杏愛' 在 9211517178396800396_0.dem "
    "无位置、在 9220453964224116108_0.dem 可回放），证明是逐广播的数据缺失，与玩家本身无关。",
    "影响范围：6 部 demo 共 60 个玩家位次，7 个受影响（de_ancient 2、de_inferno 1+4、de_mirage 0）。"
    "受影响玩家仍可完整计算事件类统计（击杀/死亡/ADR/Rating），仅位置类功能（2D 回放、热力图、"
    "偏好位置）不可用。",
]

DEFAULT_KNOWN_LIMITS: list[str] = [
    "Team 0 玩家（spawn 事件无 team_num 且未被 death/hurt 队伍名补齐）：无法回放、无位置分析、RWS=0。",
    "WMPVP SourceTV 无 player_info 表，名单由 player_spawn 重建（已实现 fallback）。",
    "部分 demo 无 round_start 事件，回合边界由 round_end 推导（已实现 fallback）。",
]


def render_coverage_report(
    demos: list[DemoCoverage],
    out_path: str | Path,
    conclusions: list[str] | None = None,
    known_limits: list[str] | None = None,
    title: str = "CS2 Demo 解析覆盖度报告",
) -> Path:
    """Render the coverage report to an HTML file (human-verifiable artifact)."""
    from datetime import datetime

    from jinja2 import Environment, FileSystemLoader

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))
    template = env.get_template("coverage.html")

    ok = [d for d in demos if d.status == "ok"]
    report = {
        "title": title,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "demos": demos,
        "ok_demos": len(ok),
        "error_demos": len(demos) - len(ok),
        "total_team_zero": sum(len(d.team_zero_players) for d in demos),
        "total_replayable": sum(len(d.replayable_players) for d in demos),
        "conclusions": DEFAULT_CONCLUSIONS if conclusions is None else conclusions,
        "known_limits": DEFAULT_KNOWN_LIMITS if known_limits is None else known_limits,
    }
    html = template.render(report=report)
    out_path.write_text(html, encoding="utf-8")
    logger.info("coverage report written -> %s", out_path)
    return out_path
