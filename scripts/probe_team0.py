"""Investigate players missing per-tick position data (Team 0 / non-replayable).

Phase 1b of LTG-3: for every player whose coverage scan says has_position=False,
gather evidence about WHY demoparser2 did not track them:
  - do they appear in the ticks table at all? (steamid present / X NaN ratio)
  - do they have spawn / death / hurt / fire events? (active in the match?)
  - what team_num do their (missing) ticks carry?

Read-only: loads demos from cache, prints findings.
Usage: python scripts/probe_team0.py demos/*.dem
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from cs_analyzer.cache import DemoCache
from cs_analyzer.coverage import _player_position_stats
from cs_analyzer.parser.manager import ParseManager


def count_events(events: dict[str, pd.DataFrame], table: str, sid: str, cols: tuple[str, ...]) -> int:
    df = events.get(table)
    if df is None or df.empty:
        return 0
    total = 0
    for col in cols:
        if col in df.columns:
            total += int((df[col].astype(str) == sid).sum())
    return total


def probe(demo, cache_dir: Path) -> None:
    path = demo.metadata.demo_path
    print(f"\n=== {path.split(chr(92))[-1]}  map={demo.metadata.map_name} ===")
    pos = _player_position_stats(demo)
    ticks = demo.ticks
    tick_sids = set(ticks["steamid"].astype(str).unique()) if not ticks.empty else set()
    for p in demo.players:
        has_pos, ratio = pos.get(p.steamid, (False, 0.0))
        if has_pos:
            continue
        print(f"\n  [NON-REPLAYABLE] {p.name!r} steamid={p.steamid} team={p.team}")
        sub = ticks[ticks["steamid"].astype(str) == p.steamid] if not ticks.empty else pd.DataFrame()
        print(f"    ticks rows: {len(sub)}  | in ticks table: {p.steamid in tick_sids}")
        if not sub.empty:
            x = sub["X"].to_numpy(dtype=float)
            import numpy as np
            non_na = int(np.isfinite(x).sum())
            print(f"      X non-NaN: {non_na}/{len(x)}")
            if "team_num" in sub.columns:
                print(f"      team_num values: {sub['team_num'].dropna().unique().tolist()[:6]}")
            if "is_alive" in sub.columns:
                print(f"      is_alive true: {int(sub['is_alive'].fillna(False).astype(bool).sum())}")
        print(f"    events: spawn={count_events(demo.events,'player_spawn',p.steamid,('user_steamid',))} "
              f"death(user/atk)={count_events(demo.events,'player_death',p.steamid,('user_steamid','attacker_steamid'))} "
              f"hurt(us/atk)={count_events(demo.events,'player_hurt',p.steamid,('user_steamid','attacker_steamid'))} "
              f"fire={count_events(demo.events,'weapon_fire',p.steamid,('user_steamid',))}")
        # player_info sanity: does the backend player-info table know them?
        for t in ("player_spawn",):
            df = demo.events.get(t)
            if df is not None and not df.empty and "user_steamid" in df.columns:
                rows = df[df["user_steamid"].astype(str) == p.steamid]
                if not rows.empty:
                    print(f"      spawn rows: {len(rows)}; user_team_num unique: "
                          f"{rows.get('user_team_num', pd.Series(dtype=float)).dropna().unique().tolist()[:6]}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cache = DemoCache(Path(".cache"))
    manager = ParseManager(cache=cache)
    for arg in sys.argv[1:]:
        for p in sorted(Path(".").glob(arg)):
            if p.suffix.lower() != ".dem":
                continue
            demo = manager.parse(p, use_cache=True)
            probe(demo, Path(".cache"))


if __name__ == "__main__":
    main()
