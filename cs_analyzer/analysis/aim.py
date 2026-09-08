"""Aim discipline (枪法纪律, Phase I F3) — Leetify-style foundation.

weapon_fire joined to per-tick state via merge_asof on the shooter's own
sorted slice:
  - shots_fired, fire->kill conversion (same weapon within 32 ticks)
  - movement-state shares at fire time: walking / scoped / crouching
  - first-shot latency after freeze end

Graceful: when the tick table lacks a needed column the affected fields
zero out instead of failing (mirrors viewer_data's ammo-flag stance).
"""
from __future__ import annotations

import logging

import pandas as pd
from pydantic import Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.replay.timeline import round_freeze_ends
from cs_analyzer.analysis.weapons import canonical

logger = logging.getLogger(__name__)

KILL_WINDOW_TICKS = 32  # ~0.5s: fire -> kill with the same weapon


class AimResult(AnalysisResult):
    players: list[dict] = Field(default_factory=list)


@register_module
class AimModule(AnalysisModule):
    name = "aim"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        res = AimResult(module=self.name, demo_hash=demo.metadata.demo_hash)
        fires = demo.events.get("weapon_fire")
        if fires is None or fires.empty:
            return res
        rounds = demo.regular_rounds
        start_tick = rounds[0].start_tick if rounds else 0
        freeze_ends = round_freeze_ends(demo)

        # per-shooter sorted fire rows (tick, weapon)
        shots: dict[str, list[tuple[int, str]]] = {}
        for _, row in fires.iterrows():
            tick = int(row.get("tick", 0) or 0)
            if tick < start_tick:
                continue
            sid = clean_sid(row.get("user_steamid", ""))
            if not sid:
                continue
            shots.setdefault(sid, []).append((tick, canonical(str(row.get("weapon", "") or ""))))
        if not shots:
            return res

        # tick-state columns we join against (all optional)
        ticks = demo.ticks
        have_state = (
            ticks is not None and not ticks.empty
            and {"steamid", "tick"} <= set(ticks.columns)
        )
        state_cols = [c for c in ("is_walking", "is_scoped", "duck_amount")
                      if have_state and c in ticks.columns]

        kills_by_shooter = self._kills_index(demo)

        out = []
        for sid, rows in shots.items():
            rows.sort()
            n = len(rows)
            kill_ticks = kills_by_shooter.get(sid, [])

            converted = 0
            kill_ticks = kills_by_shooter.get(sid, [])
            matched_kills: set[int] = set()  # each kill claimed by one shot
            for t, w in rows:
                limit = t + KILL_WINDOW_TICKS
                for kt, kw in self._iter_after(kill_ticks, t):
                    if kt > limit:
                        break
                    if kw == w and kt not in matched_kills:
                        matched_kills.add(kt)
                        converted += 1
                        break

            # first-shot latency: first shot after each round's freeze end
            latencies: list[float] = []
            if freeze_ends:
                fe_sorted = sorted(freeze_ends.values())
                import bisect
                shot_ticks = [t for t, _ in rows]
                for fe in fe_sorted:
                    i = bisect.bisect_right(shot_ticks, fe)
                    if i < n:
                        latencies.append((shot_ticks[i] - fe) / 64.0)

            entry = {
                "steamid": sid,
                "name": "",
                "shots_fired": n,
                "fire_kills": converted,
                "fire_kill_rate": round(converted / n, 3) if n else 0.0,
                "avg_first_shot_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
            }

            if have_state and state_cols:
                shares = self._movement_shares(ticks, sid, rows, state_cols)
                entry.update(shares)
                names = {p.steamid: p.name for p in demo.players}
                entry["name"] = names.get(sid, sid)
            out.append(entry)

        out.sort(key=lambda x: -x["shots_fired"])
        res.players = out
        return res

    @staticmethod
    def _kills_index(demo: ParsedDemo) -> dict[str, list[tuple[int, str]]]:
        """shooter -> sorted [(kill_tick, canonical_weapon)]."""
        from cs_analyzer.analysis.basic_stats import BasicStatsModule

        deaths = demo.events.get("player_death")
        if deaths is None or deaths.empty:
            return {}
        deaths = BasicStatsModule._filter_warmup(deaths)
        deaths = BasicStatsModule._exclude_teamkills(deaths)
        idx: dict[str, list[tuple[int, str]]] = {}
        for _, row in deaths.iterrows():
            sid = clean_sid(row.get("attacker_steamid", ""))
            if not sid:
                continue
            idx.setdefault(sid, []).append(
                (int(row.get("tick", 0) or 0), canonical(str(row.get("weapon", "") or "")))
            )
        for v in idx.values():
            v.sort()
        return idx

    @staticmethod
    def _iter_after(sorted_pairs: list[tuple[int, str]], t: int):
        """Yield pairs with key >= t from an already-sorted list."""
        import bisect
        keys = [k for k, _ in sorted_pairs]
        for i in range(bisect.bisect_left(keys, t), len(sorted_pairs)):
            yield sorted_pairs[i]

    def _movement_shares(
        self, ticks: pd.DataFrame, sid: str,
        rows: list[tuple[int, str]], state_cols: list[str],
    ) -> dict[str, float | None]:
        """Share of shots fired while walking / scoped / crouched."""
        sub = ticks[ticks["steamid"] == sid].sort_values("tick")
        if sub.empty:
            return {}
        tt = sub["tick"].to_numpy()
        n = len(rows)
        counts = {c: 0 for c in state_cols}
        arrays = {c: sub[c].to_numpy() for c in state_cols}
        for t, _ in rows:
            i = int(pd.Series(tt).searchsorted(t, side="right")) - 1
            if i < 0:
                continue
            for c in state_cols:
                v = arrays[c][i]
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if fv != fv:  # NaN
                    continue
                if c == "duck_amount":
                    if fv > 0.5:
                        counts[c] += 1
                elif fv > 0.5:  # boolean-ish flags as floats
                    counts[c] += 1
        return {
            ("walk_share" if c == "is_walking" else
             "scope_share" if c == "is_scoped" else "crouch_share"): (
                round(counts[c] / n, 3) if n else None)
            for c in state_cols
        }
