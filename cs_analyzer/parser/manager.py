"""Parse manager: orchestrates provider detection, parsing, and caching."""
from __future__ import annotations

import logging
from pathlib import Path

from cs_analyzer.cache import DemoCache
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.parser.backend import DemoParserBackend
from cs_analyzer.parser.providers import DemoProvider, DEFAULT_PROVIDER_CHAIN, detect_provider

logger = logging.getLogger(__name__)


class ParseManager:
    """Top-level entry for parsing a .dem file into a ParsedDemo.

    Handles: cache lookup, provider detection, backend parsing, provider normalization.
    """

    def __init__(
        self,
        backend: DemoParserBackend | None = None,
        cache: DemoCache | None = None,
        provider_chain: list[DemoProvider] | None = None,
    ) -> None:
        self.backend = backend or DemoParserBackend(
            tick_fields=[
                "X", "Y", "Z",
                "pitch", "yaw",
                "health", "armor",
                "velocity", "velocity_X", "velocity_Y", "velocity_Z",
                "active_weapon", "active_weapon_name", "is_alive",
                "is_scoped", "is_walking", "duck_amount",
                "team_num", "player_name",
                # demoparser2 >= 0.42 (probe: output/.ammo_probe.json — all 8
                # WMPVP demos materialize both; backend falls back to the
                # legacy list if a future version drops them)
                "active_weapon_ammo", "is_in_reload",
                # Phase I: weapon-held-over-time (probe 2026-08-25: parses OK
                # on all real WMPVP demos; `money` stays OUT — confirmed
                # MISSING on 0.42, see output/.event_probe.json)
                "inventory",
            ]
        )
        self.cache = cache
        self.provider_chain = provider_chain or DEFAULT_PROVIDER_CHAIN

    def parse(
        self,
        dem_path: str | Path,
        use_cache: bool = True,
        force_provider: str | None = None,
    ) -> ParsedDemo:
        """Parse a .dem file, with optional caching.

        Args:
            dem_path: path to the .dem file
            use_cache: if True, return cached result if available; save new parses
            force_provider: provider kind string ("faceit", "valve", ...) to skip detection
        """
        dem_path = Path(dem_path)
        if not dem_path.exists():
            raise FileNotFoundError(f"Demo file not found: {dem_path}")

        demo_hash = DemoCache.hash_demo(dem_path)

        # Cache lookup
        if use_cache and self.cache is not None:
            cached = self.cache.load(demo_hash)
            if cached is not None:
                logger.info("cache hit for %s (%s)", dem_path.name, demo_hash[:12])
                return cached

        # Provider detection (quick header read)
        if force_provider:
            provider = self._find_provider_by_kind(force_provider)
        else:
            header = self.backend.read_header(dem_path)
            provider = detect_provider(header, self.provider_chain)
        logger.info("parsing %s as %s", dem_path.name, provider.kind().value)

        # Full parse
        demo = self.backend.parse(dem_path, demo_hash)

        # Provider normalization
        demo = provider.parse(demo)

        # Cache write
        if use_cache and self.cache is not None:
            try:
                self.cache.save(demo_hash, demo)
                logger.info("cached %s -> %s", demo_hash[:12], self.cache.path_for(demo_hash))
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache save failed for %s: %s", demo_hash[:12], exc)

        return demo

    def _find_provider_by_kind(self, kind: str) -> DemoProvider:
        for p in self.provider_chain:
            if p.kind().value == kind.lower():
                return p
        raise ValueError(
            f"Unknown provider '{kind}'. Available: {[p.kind().value for p in self.provider_chain]}"
        )
