"""Exporter base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Exporter(ABC):
    """Base class for exporters. Produces final output files from render artifacts."""

    @abstractmethod
    def export(self, input_path: Path, output_path: Path) -> Path:
        """Transform input artifact into final output. Returns output path."""
