"""Report exporter: JSON and HTML analysis reports."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from cs_analyzer.analysis.basic_stats import BasicStatsResult
from cs_analyzer.analysis.ratings import RatingsResult
from cs_analyzer.export.base import Exporter

logger = logging.getLogger(__name__)


class ReportExporter(Exporter):
    """Export analysis results as JSON or HTML."""

    def __init__(self, basic: BasicStatsResult | None = None, ratings: RatingsResult | None = None) -> None:
        self.basic = basic
        self.ratings = ratings

    def export(self, input_path: str | Path | None, output_path: str | Path) -> Path:
        """Write a report. `input_path` is unused (data comes from constructor)."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.suffix == ".json":
            return self._export_json(output_path)
        if output_path.suffix in (".html", ".htm"):
            return self._export_html(output_path)
        raise ValueError(f"Unsupported report format: {output_path.suffix}")

    def _export_json(self, path: Path) -> Path:
        data = self._build_report_data()
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("exported JSON report -> %s", path)
        return path

    def _export_html(self, path: Path) -> Path:
        data = self._build_report_data()
        html = self._render_html(data)
        path.write_text(html, encoding="utf-8")
        logger.info("exported HTML report -> %s", path)
        return path

    def _build_report_data(self) -> dict:
        players = []
        if self.basic is not None:
            for bs in self.basic.players:
                rt = self.ratings.by_steamid(bs.steamid) if self.ratings else None
                players.append({
                    "name": bs.name,
                    "team": bs.team,
                    "kills": bs.kills,
                    "deaths": bs.deaths,
                    "assists": bs.assists,
                    "headshot_kills": bs.headshot_kills,
                    "first_kills": bs.first_kills,
                    "damage": bs.damage,
                    "rounds": bs.rounds,
                    "KPR": round(bs.KPR, 3),
                    "ADR": round(bs.ADR, 1),
                    "Survivals": round(bs.Survivals, 3),
                    "Headshot_pct": round(bs.headshot_pct, 1),
                    "FirstKillsPerRound": round(bs.FirstKillsPerRound, 3),
                    "RWS": round(rt.RWS, 2) if rt else None,
                    "Rating": round(rt.Rating, 3) if rt else None,
                    "KAST": round(rt.KAST, 1) if rt else None,
                    "Impact": round(rt.Impact, 3) if rt else None,
                })
        return {
            "demo_hash": self.basic.demo_hash if self.basic else "",
            "players": players,
        }

    @staticmethod
    def _render_html(data: dict) -> str:
        rows = []
        for p in data["players"]:
            rows.append(
                "<tr>"
                + "".join(f"<td>{p.get(k, '')}</td>" for k in (
                    "name", "team", "kills", "deaths", "assists",
                    "KPR", "ADR", "Headshot_pct", "RWS", "Rating",
                ))
                + "</tr>"
            )
        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Demo Report</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
th {{ background: #f4f4f4; }}
tr:nth-child(even) {{ background: #fafafa; }}
</style></head><body>
<h1>Demo Analysis Report</h1>
<p>Demo hash: <code>{data["demo_hash"]}</code></p>
<table>
<thead><tr>
<th>Name</th><th>Team</th><th>Kills</th><th>Deaths</th><th>Assists</th>
<th>KPR</th><th>ADR</th><th>HS%</th><th>RWS</th><th>Rating</th>
</tr></thead>
<tbody>
{"".join(rows)}
</tbody></table>
</body></html>"""
