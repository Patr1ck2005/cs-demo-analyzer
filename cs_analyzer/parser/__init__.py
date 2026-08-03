"""Layer 1: Demo parsing.

- DemoParserBackend: demoparser2 wrapper, provider-agnostic raw parse
- DemoProvider: source-specific detection + normalization
- ParseManager: orchestrates provider chain + caching
"""
from cs_analyzer.parser.backend import DemoParserBackend
from cs_analyzer.parser.manager import ParseManager
from cs_analyzer.parser.providers import (
    DEFAULT_PROVIDER_CHAIN,
    DemoProvider,
    FaceitProvider,
    PerfectWorldProvider,
    ValveProvider,
)

__all__ = [
    "DEFAULT_PROVIDER_CHAIN",
    "DemoParserBackend",
    "DemoProvider",
    "FaceitProvider",
    "ParseManager",
    "PerfectWorldProvider",
    "ValveProvider",
]
