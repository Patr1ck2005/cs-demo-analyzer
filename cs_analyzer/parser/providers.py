"""Demo providers: source-specific detection and normalization.

All platforms (Valve MM, Faceit, ESEA, 5EPlay, PerfectWorld) use the same
Valve demo format. Providers differ only in:
  1. Detection (from header server_name / client_name)
  2. Normalization (warmup handling, match_id format, team naming)

The actual parsing is done by DemoParserBackend; providers wrap its output.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import ProviderKind, Round, Team

logger = logging.getLogger(__name__)

# MR12: teams switch sides after round 12 (regulation). Overtime uses MR6.
_REGULATION_ROUNDS = 12
_OVERTIME_ROUNDS = 6


class DemoProvider(ABC):
    """Base class for demo source providers."""

    @abstractmethod
    def kind(self) -> ProviderKind:
        """The provider kind this class handles."""

    @abstractmethod
    def detect(self, header: dict) -> bool:
        """Return True if the header matches this provider's demos."""

    def parse(self, demo: ParsedDemo) -> ParsedDemo:
        """Hook to adjust a parsed demo. Default: set provider kind + normalize."""
        demo.data.metadata.provider = self.kind()
        self.normalize(demo)
        return demo

    def normalize(self, demo: ParsedDemo) -> ParsedDemo:
        """Common normalization: drop warmup, fill team names on rounds."""
        if not demo.data.rounds:
            return demo

        # Filter warmup rounds if configured (caller may re-enable)
        # We keep warmup rounds in the data but mark them; callers filter via
        # `regular_rounds` property. This preserves info without forcing a choice.

        # Assign team names to rounds based on starting side + halftime switch.
        team_a = demo.data.metadata.team_a
        team_b = demo.data.metadata.team_b
        if team_a.name and team_b.name:
            self._fill_round_winners(demo, team_a, team_b)

        return demo

    def _fill_round_winners(self, demo: ParsedDemo, team_a: Team, team_b: Team) -> None:
        """Map round winner_side (T/CT) to team name, accounting for side swaps."""
        a_starts = team_a.starting_side  # "CT" or "T"
        b_starts = "T" if a_starts == "CT" else "CT"

        for rnd in demo.data.rounds:
            if rnd.is_warmup:
                continue
            a_side, b_side = self._sides_for_round(rnd, a_starts, b_starts)
            if rnd.winner_side == a_side:
                rnd.winner = team_a.name
            elif rnd.winner_side == b_side:
                rnd.winner = team_b.name

    def _sides_for_round(self, rnd: Round, a_starts: str, b_starts: str) -> tuple[str, str]:
        """Determine each team's side in a given round (halftime swap)."""
        reg_num = rnd.number
        if rnd.is_overtime:
            # Overtime: sides swap every _OVERTIME_ROUNDS after regulation
            ot_num = reg_num - _REGULATION_ROUNDS
            swap = (ot_num - 1) // _OVERTIME_ROUNDS
        else:
            swap = 0 if reg_num <= _REGULATION_ROUNDS else 1

        if swap % 2 == 0:
            return a_starts, b_starts
        return b_starts, a_starts


class ValveProvider(DemoProvider):
    """Valve Matchmaking demos. Default fallback provider."""

    def kind(self) -> ProviderKind:
        return ProviderKind.VALVE

    def detect(self, header: dict) -> bool:
        server = (header.get("server_name") or "").lower()
        client = (header.get("client_name") or "").lower()
        return "valve" in server or "valve" in client


class FaceitProvider(DemoProvider):
    """Faceit platform demos."""

    _patterns = (r"faceit", r"\bfaceit\b", r"faceit\.com")

    def kind(self) -> ProviderKind:
        return ProviderKind.FACEIT

    def detect(self, header: dict) -> bool:
        blob = " ".join([
            str(header.get("server_name") or ""),
            str(header.get("client_name") or ""),
            str(header.get("game_directory") or ""),
        ]).lower()
        return any(re.search(p, blob) for p in self._patterns)


class PerfectWorldProvider(DemoProvider):
    """完美世界平台 (Perfect World CS2 platform)."""

    _patterns = (r"perfect", r"完美", r"pwcs2", r"5eplay", r"\b5e\b")

    def kind(self) -> ProviderKind:
        return ProviderKind.PERFECT_WORLD

    def detect(self, header: dict) -> bool:
        blob = " ".join([
            str(header.get("server_name") or ""),
            str(header.get("client_name") or ""),
            str(header.get("game_directory") or ""),
        ]).lower()
        return any(re.search(p, blob) for p in self._patterns)


# Provider chain in priority order. First match wins. Valve is the fallback.
DEFAULT_PROVIDER_CHAIN: list[DemoProvider] = [
    FaceitProvider(),
    PerfectWorldProvider(),
    ValveProvider(),
]


def detect_provider(header: dict, chain: list[DemoProvider] | None = None) -> DemoProvider:
    """Return the first provider whose detect() matches the header."""
    chain = chain or DEFAULT_PROVIDER_CHAIN
    for provider in chain:
        if provider.detect(header):
            return provider
    return chain[-1]  # fallback (Valve)
