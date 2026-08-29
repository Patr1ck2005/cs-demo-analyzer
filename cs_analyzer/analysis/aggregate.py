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
    # Phase H career-page extensions (additive; weighted sums for averages)
    total_headshot_kills: int = 0
    total_first_kills: int = 0
    total_survival_weighted: float = 0.0  # Survivals x rounds, for the weighted mean
    # Phase I (B3): pooled damage for round-weighted avg_adr
    total_damage: int = 0

    @property
    def demo_count(self) -> int:
        return len(self.demos)

    @property
    def avg_kpr(self) -> float:
        return self.total_kills / self.total_rounds if self.total_rounds else 0.0

    @property
    def avg_adr(self) -> float:
        # round-weighted: total damage / total rounds (B3 fix — a plain mean
        # let a 4-round demo weigh the same as a 30-round one)
        return self.total_damage / self.total_rounds if self.total_rounds else 0.0

    def _round_weighted(self, key: str) -> float:
        # Rating/KAST are non-additive, so pool as Σ(x·rounds)/Σrounds instead
        # of recomputing the HLTV blend cross-demo.
        num = sum(d[key] * d["rounds"] for d in self.demos if d.get("rounds"))
        den = sum(d["rounds"] for d in self.demos if d.get("rounds"))
        return num / den if den else 0.0

    @property
    def avg_rating(self) -> float:
        return self._round_weighted("Rating")

    @property
    def avg_kast(self) -> float:
        return self._round_weighted("KAST")

    @property
    def avg_hs_pct(self) -> float:
        return (self.total_headshot_kills / self.total_kills * 100.0) if self.total_kills else 0.0

    @property
    def avg_fkpr(self) -> float:
        return self.total_first_kills / self.total_rounds if self.total_rounds else 0.0

    @property
    def avg_survivals(self) -> float:
        return (self.total_survival_weighted / self.total_rounds) if self.total_rounds else 0.0


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
    match_id: str | None = None  # Phase I: WMPVP filename prefix (chronology)

    @property
    def match_key(self) -> tuple:
        """Chronological sort key — prefixed files first by id, then others
        by filename (mirrors web.store.match_key)."""
        if self.match_id:
            try:
                return (0, int(self.match_id), "")
            except ValueError:
                pass
        return (1, 0, self.filename)


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
        match_id=getattr(demo.metadata, "match_id", None),
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
            row.total_headshot_kills += bs.headshot_kills
            row.total_first_kills += bs.first_kills
            row.total_survival_weighted += bs.Survivals * bs.rounds
            row.total_damage += bs.damage
            row.demos.append(
                {
                    "demo": Path(demo.metadata.demo_path).name,
                    "demo_hash": demo.metadata.demo_hash,
                    "map_name": demo.metadata.map_name,
                    "rounds": bs.rounds,
                    "kills": bs.kills,
                    "deaths": bs.deaths,
                    "KPR": bs.KPR,
                    "ADR": bs.ADR,
                    "damage": bs.damage,
                    "Rating": rt.Rating if rt else 0.0,
                    "KAST": rt.KAST if rt else 0.0,
                    "RWS": rt.RWS if rt else 0.0,
                }
            )
    ordered = sorted(players.values(), key=lambda p: p.avg_rating, reverse=True)
    demo_rows.sort(key=lambda d: d.match_key)
    return AggregateResult(players=ordered, demos=demo_rows)
