"""Economy analysis (Phase F M7): per-round team buy classification + trends.

The purchase aggregation lives here (build_purchase_log) and is shared with
the viewer layers artifact (viewer_data._economy_events consumes it), so the
web replay and this module always agree on spend numbers.
"""
from __future__ import annotations

import logging

import pandas as pd
from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid, round_player_sides
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

# team average spend thresholds (V1 heuristic; HLTV-style boundaries)
ECO_MAX = 2000
FORCE_MAX = 3700

_GRENADE_PREFIXES = ("smoke", "flash", "hegrenade", "molotov", "incendiary", "decoy")


def _short_weapon(name) -> str:
    n = str(name or "").strip()
    if n.startswith("weapon_"):
        n = n[len("weapon_"):]
    return n


def build_purchase_log(demo: ParsedDemo) -> dict[int, dict[str, dict]]:
    """item_purchase rows -> {round_number: {steamid: {spend, weapons, nades}}}.

    Shared source of truth for the viewer economy layer and this module.
    """
    df = demo.events.get("item_purchase")
    rounds: dict[int, dict[str, dict]] = {}
    if df is None or df.empty:
        return rounds
    bounds = [(int(r.start_tick), int(r.end_tick)) for r in demo.regular_rounds]

    def round_at(tick: int) -> int:
        for i, (start, end) in enumerate(bounds):
            if start <= tick <= end:
                return i + 1
        return 0

    for _, row in df.iterrows():
        rnd = round_at(int(row.get("tick", 0) or 0))
        if rnd == 0:
            continue
        sid = clean_sid(row.get("steamid") or row.get("user_steamid") or "")
        if not sid:
            continue
        item = _short_weapon(row.get("item_name", row.get("weapon", "")))
        cost = int(row.get("cost", 0) or 0)
        bucket = rounds.setdefault(rnd, {}).setdefault(
            sid, {"spend": 0, "weapons": [], "nades": 0}
        )
        bucket["spend"] += cost
        bucket["weapons"].append(item)
        if item.startswith(_GRENADE_PREFIXES):
            bucket["nades"] += 1
    return rounds


class TeamRoundBuy(BaseModel):
    """One team's buy state in one round."""
    round: int
    side: str            # "T" | "CT"
    spend: int           # team total spend
    avg_spend: float
    buy: str             # "eco" | "force" | "full"
    won: bool | None = None  # None when the round winner side is unknown


class EconomyResult(AnalysisResult):
    rounds: list[TeamRoundBuy] = Field(default_factory=list)
    # per side: streak summary + win-rate by buy type (win_rate None = no
    # samples — the frontend must not read "no eco rounds" as "0% eco wins")
    win_by_buy: dict[str, dict[str, dict[str, float | None]]] = Field(default_factory=dict)
    loss_streaks: dict[str, int] = Field(default_factory=dict)


@register_module
class EconomyModule(AnalysisModule):
    name = "economy"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        log = build_purchase_log(demo)
        rounds_out: list[TeamRoundBuy] = []

        # side per round per player: from ticks team_num majority at round start
        side_at = self._side_at_round_start(demo)
        # round winner side from regular_rounds
        winners = {r.number: r.winner_side for r in demo.regular_rounds}

        for rnd in sorted(log):
            players = log[rnd]
            team_spend: dict[str, int] = {"T": 0, "CT": 0}
            team_n: dict[str, int] = {"T": 0, "CT": 0}
            for sid, bucket in players.items():
                side = side_at.get((rnd, sid))
                if side in team_spend:
                    team_spend[side] += bucket["spend"]
                    team_n[side] += 1
            for side in ("T", "CT"):
                if team_n[side] == 0:
                    continue
                total = team_spend[side]
                avg = total / team_n[side]
                buy = "eco" if avg < ECO_MAX else "force" if avg < FORCE_MAX else "full"
                won = None
                w = winners.get(rnd)
                if w in ("T", "CT"):
                    won = w == side
                rounds_out.append(TeamRoundBuy(
                    round=rnd, side=side, spend=total, avg_spend=round(avg, 1),
                    buy=buy, won=won,
                ))

        # win-rate per buy type per side
        win_by_buy: dict[str, dict[str, dict[str, float]]] = {}
        streaks: dict[str, int] = {}
        for side in ("T", "CT"):
            side_rows = [r for r in rounds_out if r.side == side]
            by_buy: dict[str, dict[str, float]] = {}
            for buy in ("eco", "force", "full"):
                rows = [r for r in side_rows if r.buy == buy and r.won is not None]
                n = len(rows)
                w = sum(1 for r in rows if r.won)
                by_buy[buy] = {"n": float(n), "wins": float(w),
                               "win_rate": round(w / n, 3) if n else None}
            win_by_buy[side] = by_buy
            # longest loss streak (consecutive rounds with won=False)
            longest = cur = 0
            for r in sorted(side_rows, key=lambda r: r.round):
                if r.won is False:
                    cur += 1
                    longest = max(longest, cur)
                else:
                    cur = 0
            streaks[side] = longest

        return EconomyResult(
            module=self.name, demo_hash=demo.metadata.demo_hash,
            rounds=rounds_out, win_by_buy=win_by_buy, loss_streaks=streaks,
        )

    def _side_at_round_start(self, demo: ParsedDemo) -> dict[tuple[int, str], str]:
        """(round, steamid) -> "T"|"CT".

        Single source of truth: util.round_player_sides (majority team_num
        over the round's tick span, swap-safe). The previous private
        implementation (first-256-tick last-wins) disagreed with it on
        half-buy/swap demos, which split funlab vs economy eco classes.
        """
        sides = round_player_sides(demo)
        out: dict[tuple[int, str], str] = {}
        for rnd, per_sid in sides.items():
            for sid, side in per_sid.items():
                out[(rnd, sid)] = side
        return out
