"""Phase T2 — process-pool whole-library scan (config-gated, Windows spawn).

One real-spawn test: the module-level workers must survive pickling by
qualified name and produce results identical to the thread path. Kept to a
single test (spawn costs ~10s); everything else exercises the default
thread executor.
"""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis.aggregate import compute_aggregate
from tests.conftest import build_parsed_demo


def _tiny_cache(tmp_path, second_player: bool = False):
    from cs_analyzer.cache import DemoCache

    sids = ["76561111111110001", "76561111111110002"] if second_player \
        else ["76561111111110001"]
    cache = DemoCache(tmp_path / "cache")
    for i, h in enumerate(("aaaa", "bbbb")):
        n = len(sids)
        ticks = pd.DataFrame({
            "tick": [0, 640, 1280][:n],
            "steamid": sids,
            "X": [float(i), 1.0, 2.0][:n],
            "Y": [0.0] * n,
            "is_alive": [True] * n,
            "team_num": [3.0] * n,
        })
        events = {"player_death": pd.DataFrame({
            "tick": [500],
            "attacker_name": ["Alice"],
            "user_name": ["Carol"],
            "attacker_steamid": [sids[0]],
            "user_steamid": ["76561111111110003"],
            "assister_steamid": [""],
            "weapon": ["ak47"],
            "headshot": [False],
            "penetrated": [False],
            "thrusmoke": [False],
            "noscope": [False],
            "attackerinair": [False],
        })}
        demo = build_parsed_demo(ticks=ticks, events=events)
        demo.metadata.demo_hash = h
        cache.save(h, demo)
    return cache


def test_process_executor_matches_thread(tmp_path):
    cache = _tiny_cache(tmp_path, second_player=True)
    res_thread = compute_aggregate(cache.cache_dir, executor="thread")
    res_proc = compute_aggregate(cache.cache_dir, executor="process")
    assert res_proc.total_demos == res_thread.total_demos == 2
    assert res_proc.total_players == res_thread.total_players
    by_sid_t = {p.steamid: p for p in res_thread.players}
    by_sid_p = {p.steamid: p for p in res_proc.players}
    assert set(by_sid_t) == set(by_sid_p)
    for sid, p in by_sid_t.items():
        q = by_sid_p[sid]
        assert (q.total_kills, q.total_rounds, q.total_damage) == \
               (p.total_kills, p.total_rounds, p.total_damage)
        assert q.demo_count == p.demo_count


def test_settings_scan_executor_validation():
    from cs_analyzer.config import Settings
    import pytest

    assert Settings(scan_executor="thread").scan_executor == "thread"
    assert Settings(scan_executor="PROCESS").scan_executor == "process"
    with pytest.raises(Exception):
        Settings(scan_executor="fork")
