"""Cross-demo aggregation (LTG-2 stage 2): player identity, team comparison, trends.

Pure data computation from cached ParsedDemo objects; the web UI renders charts
from AggregateResult. Player identity is matched by steamid across demos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cs_analyzer.cache import DemoCache
from cs_analyzer.config import AnalysisConfig
from cs_analyzer.analysis import AnalysisRunner


@dataclass
class PlayerRow:
    steamid: str
    name: str
    demos: list[dict] = field(default_factory=list)  # per-demo stats
    total_kills: int = 0
    total_deaths: int = 0
    total_rounds: int = 0

    @property
    def demo_count(self) -> int:
        return len(self.demos)

    @property
    def avg_kpr(self) -> float:
        return self.total_kills / self.total_rounds if self.total_rounds else 0.0

    @property
    def avg_adr(self) -> float:
        vals = [d["ADR"] for d in self.demos if d.get("rounds")]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_rating(self) -> float:
        vals = [d["Rating"] for d in self.demos if d.get("rounds")]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_kast(self) -> float:
        vals = [d["KAST"] for d in self.demos if d.get("rounds")]
        return sum(vals) / len(vals) if vals else 0.0


@dataclass
class DemoRow:
    demo_hash: str
    filename: str
    map_name: str
    rounds: int
    t_score: int
    ct_score: int
    t_win_rate: float = 0.0  # 0..1
    trend: list[dict] = field(default_factory=list)  # [{round, winner_side, t_score, ct_score}]


@dataclass
class AggregateResult:
    players: list[PlayerRow] = field(default_factory=list)
    demos: list[DemoRow] = field(default_factory=list)

    @property
    def total_demos(self) -> int:
        return len(self.demos)

    @property
    def total_players(self) -> int:
        return len(self.players)


def _demo_row(demo) -> DemoRow:
    reg = demo.regular_rounds
    t_score = reg[-1].t_score if reg else 0
    ct_score = reg[-1].ct_score if reg else 0
    t_wins = sum(1 for r in reg if r.winner_side == "T")
    trend = [
        {
            "round": r.number,
            "winner_side": r.winner_side,
            "t_score": r.t_score,
            "ct_score": r.ct_score,
        }
        for r in reg
    ]
    return DemoRow(
        demo_hash=demo.metadata.demo_hash,
        filename=Path(demo.metadata.demo_path).name,
        map_name=demo.metadata.map_name,
        rounds=len(reg),
        t_score=t_score,
        ct_score=ct_score,
        t_win_rate=t_wins / len(reg) if reg else 0.0,
        trend=trend,
    )


def compute_aggregate(cache_dir: Path = Path(".cache"), analysis: AnalysisConfig | None = None) -> AggregateResult:
    """Compute cross-demo aggregation from all cached demos."""
    cache = DemoCache(cache_dir)
    runner = AnalysisRunner(analysis or AnalysisConfig(enabled_modules=["basic_stats", "ratings"]))

    players: dict[str, PlayerRow] = {}
    demo_rows: list[DemoRow] = []
    for demo_dir in sorted(cache_dir.glob("*")):
        if not demo_dir.is_dir():
            continue
        demo = cache.load(demo_dir.name)
        if demo is None:
            continue
        results = runner.run(demo)
        basic = results.get("basic_stats")
        ratings = results.get("ratings")
        demo_rows.append(_demo_row(demo))
        if basic is None or ratings is None:
            continue
        for bs in basic.players:
            rt = ratings.by_steamid(bs.steamid)
            row = players.setdefault(bs.steamid, PlayerRow(steamid=bs.steamid, name=bs.name))
            row.name = bs.name
            row.total_kills += bs.kills
            row.total_deaths += bs.deaths
            row.total_rounds += bs.rounds
            row.demos.append(
                {
                    "demo": Path(demo.metadata.demo_path).name,
                    "rounds": bs.rounds,
                    "kills": bs.kills,
                    "KPR": bs.KPR,
                    "ADR": bs.ADR,
                    "Rating": rt.Rating if rt else 0.0,
                    "KAST": rt.KAST if rt else 0.0,
                    "RWS": rt.RWS if rt else 0.0,
                }
            )
    ordered = sorted(players.values(), key=lambda p: p.avg_rating, reverse=True)
    return AggregateResult(players=ordered, demos=demo_rows)
