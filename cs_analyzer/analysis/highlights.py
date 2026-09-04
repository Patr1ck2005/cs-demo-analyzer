"""Highlight moments (高光时刻, Phase H M5): multi-kills and clutch rounds.

From player_death grouped per round:
- multi-kills: kills by one attacker in one round -> 2k/3k/4k/ACE
- clutches: the round's winner side is down to its last player while the
  opponent still has >=2 alive -> 1vN (N = opponent alive count at that
  moment); a clutch is only counted when that side wins the round.

Pure event derivation — no per-tick scanning.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid, round_player_sides
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

# display ordering weight: bigger moments first, then chronological
_TIER_RANK = {"ace": 0, "k4": 1, "1v4": 2, "k3": 3, "1v3": 4, "k2": 5, "1v2": 6}


class Highlight(BaseModel):
    kind: str  # "multi_kill" | "clutch"
    tier: str  # "k2","k3","k4","ace" | "1v2".."1v5"
    round: int
    steamid: str
    name: str
    side: str  # "T" | "CT" (player's side in that round)
    kills: int
    score_t: int = 0
    score_ct: int = 0
    demo_hash: str = ""
    map_name: str = ""


class HighlightsResult(AnalysisResult):
    highlights: list[Highlight] = Field(default_factory=list)

    def sorted(self) -> list[Highlight]:
        return sorted(
            self.highlights,
            key=lambda h: (_TIER_RANK.get(h.tier, 99), h.round),
        )


@register_module
class HighlightsModule(AnalysisModule):
    name = "highlights"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        out: list[Highlight] = []
        deaths = demo.events.get("player_death")
        rounds = [r for r in demo.regular_rounds if not getattr(r, "is_warmup", False)]
        if deaths is None or deaths.empty or not rounds:
            return HighlightsResult(module=self.name, demo_hash=demo.metadata.demo_hash)

        # roster names as fallback (event attacker_name can be blank on some
        # broadcasts); prefer the roster's display name
        roster_names = {p.steamid: p.name for p in demo.players}

        # player side per round: majority of tick team_num within the round window
        side_of = self._round_sides(demo)

        for rnd in rounds:
            window = deaths[
                (deaths["tick"] >= rnd.start_tick) & (deaths["tick"] < rnd.end_tick)
            ]
            if window.empty:
                continue
            # ---- multi-kills (exclude suicides; attacker required) ----
            counts: dict[str, int] = {}
            names: dict[str, str] = {}
            for _, row in window.iterrows():
                att = clean_sid(row.get("attacker_steamid", ""))
                vic = clean_sid(row.get("user_steamid", ""))
                if not att or att == vic:
                    continue
                counts[att] = counts.get(att, 0) + 1
                names.setdefault(att, str(row.get("attacker_name", "") or att))
            for sid, k in counts.items():
                if k < 2:
                    continue
                tier = "ace" if k >= 5 else f"k{min(k, 4)}"
                out.append(Highlight(
                    kind="multi_kill", tier=tier, round=rnd.number,
                    steamid=sid,
                    name=names.get(sid) or roster_names.get(sid) or sid,
                    side=side_of.get(rnd.number, {}).get(sid, ""),
                    kills=k, score_t=rnd.t_score, score_ct=rnd.ct_score,
                    demo_hash=demo.metadata.demo_hash,
                    map_name=demo.metadata.map_name,
                ))

            # ---- clutch (winner side down to last man vs >=2 opponents) ----
            clutch = self._clutch(window, rnd, side_of.get(rnd.number, {}))
            if clutch is not None:
                sid, n_opp, name = clutch
                out.append(Highlight(
                    kind="clutch", tier=f"1v{min(n_opp, 5)}", round=rnd.number,
                    steamid=sid,
                    name=name if name != sid else roster_names.get(sid, sid),
                    side=side_of.get(rnd.number, {}).get(sid, ""),
                    kills=int((window["attacker_steamid"] == sid).sum()),
                    score_t=rnd.t_score, score_ct=rnd.ct_score,
                    demo_hash=demo.metadata.demo_hash,
                    map_name=demo.metadata.map_name,
                ))

        return HighlightsResult(
            module=self.name, demo_hash=demo.metadata.demo_hash, highlights=out
        )

    @staticmethod
    def _round_sides(demo: ParsedDemo) -> dict[int, dict[str, str]]:
        """round -> steamid -> "T"/"CT" — delegates to the shared swap-safe
        helper (Phase I: the old whole-round window mean broke at halftime)."""
        return round_player_sides(demo)

    @staticmethod
    def _clutch(window, rnd, side_map: dict[str, str]):
        """Walk the kill sequence; find the last-man-standing moment of the
        winning side. Returns (steamid, opponents_alive, name) or None.

        side_map: round-level steamid -> "T"/"CT" (from _round_sides); it
        seeds the alive sets so players with no kills still count as alive.
        """
        winner = rnd.winner_side  # "T" | "CT"
        if winner not in ("T", "CT"):
            return None
        loser = "CT" if winner == "T" else "T"

        names: dict[str, str] = {}
        alive: dict[str, set[str]] = {"T": set(), "CT": set()}
        for sid, s in side_map.items():
            if s in alive:
                alive[s].add(sid)

        for _, row in window.sort_values("tick").iterrows():
            att = clean_sid(row.get("attacker_steamid", ""))
            vic = clean_sid(row.get("user_steamid", ""))
            if not vic or att == vic:
                continue
            vs = side_map.get(vic, "")
            as_ = side_map.get(att, "") if att else ""
            if vs:
                alive[vs].discard(vic)
            if as_:
                names.setdefault(att, str(row.get("attacker_name", "") or att))
            # winner side down to exactly 1, opponent still >=2 -> clutch moment
            if len(alive[winner]) == 1 and len(alive[loser]) >= 2:
                sid = next(iter(alive[winner]))
                return sid, len(alive[loser]), names.get(sid, sid)
        return None
