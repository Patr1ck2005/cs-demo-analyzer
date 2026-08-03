"""Layer 3: Analysis modules.

Each module implements AnalysisModule and produces a typed AnalysisResult.
Modules are registered and run via AnalysisRunner; results are cached per demo.
"""
from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult
from cs_analyzer.analysis.basic_stats import BasicStatsModule, BasicStatsResult, PlayerStats
from cs_analyzer.analysis.preference import PlayerPreference, PreferenceModule, PreferenceResult
from cs_analyzer.analysis.ratings import PlayerRatings, RatingsModule, RatingsResult
from cs_analyzer.analysis.runner import AnalysisRunner

__all__ = [
    "AnalysisContext",
    "AnalysisModule",
    "AnalysisResult",
    "AnalysisRunner",
    "BasicStatsModule",
    "BasicStatsResult",
    "PlayerPreference",
    "PlayerRatings",
    "PlayerStats",
    "PreferenceModule",
    "PreferenceResult",
    "RatingsModule",
    "RatingsResult",
]
