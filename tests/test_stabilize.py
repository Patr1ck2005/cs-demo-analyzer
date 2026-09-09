"""Phase S stabilization tests.

S1: cache hygiene — the startup sweep must GC orphan cache entries (cache
dirs whose source .dem vanished from demos/) instead of letting them
masquerade as real matches in whole-library reports forever.
"""
from __future__ import annotations

import pytest

from cs_analyzer.web import app as web_app
from tests.conftest import build_parsed_demo


@pytest.fixture
def sweep_env(tmp_path, monkeypatch):
    """web_app wired to tmp cache/demos dirs with a reset sweep flag."""
    from cs_analyzer.cache import DemoCache

    demo = build_parsed_demo()
    demo_hash = demo.metadata.demo_hash
    cache = DemoCache(tmp_path / "cache")
    cache.save(demo_hash, demo)
    monkeypatch.setattr(web_app, "_cache", lambda: cache)
    monkeypatch.setattr(web_app, "_demos_dir", lambda: tmp_path / "demos")
    monkeypatch.setattr(web_app, "_sweep_started", False)
    # keep the re-parse arm of the sweep hermetic: no real parse of junk bytes
    monkeypatch.setattr(web_app, "_parse_job", lambda path: "stub-hash")
    return cache, tmp_path / "demos", demo_hash


def _run_sweep() -> None:
    web_app._stale_cache_sweep()


def test_sweep_gcs_orphan_cache_entry(sweep_env):
    """A cache entry with no matching demos/*.dem is removed; live entries stay."""
    cache, demos_dir, demo_hash = sweep_env
    demos_dir.mkdir(parents=True, exist_ok=True)
    (demos_dir / "some_match.dem").write_bytes(b"CSDEMO-not-a-real-demo" * 64)

    _run_sweep()

    assert not (cache.cache_dir / demo_hash).exists(), "orphan cache must be GC'd"


def test_sweep_keeps_live_cache_entries(sweep_env, monkeypatch):
    """A cache entry whose .dem IS present survives the GC."""
    import hashlib

    from cs_analyzer.cache import DemoCache

    cache, demos_dir, demo_hash = sweep_env
    # craft a .dem whose hash matches the live cache entry
    demos_dir.mkdir(parents=True, exist_ok=True)
    payload = b"CSDEMO-live" * 32
    live_hash = hashlib.sha256(payload).hexdigest()
    live_cache = DemoCache(cache.cache_dir)
    live_cache.cache_dir.mkdir(parents=True, exist_ok=True)
    (cache.cache_dir / live_hash).mkdir()
    (demos_dir / "live.dem").write_bytes(payload)

    _run_sweep()

    assert (cache.cache_dir / live_hash).exists(), "live entry must survive"
    assert not (cache.cache_dir / demo_hash).exists(), "unrelated orphan must be GC'd"


def test_sweep_gc_skipped_when_demos_dir_empty(sweep_env):
    """An emptied demos/ dir must not wipe the whole cache (guard rail)."""
    cache, demos_dir, demo_hash = sweep_env
    demos_dir.mkdir(parents=True, exist_ok=True)  # exists but no .dem files

    _run_sweep()

    assert (cache.cache_dir / demo_hash).exists(), "empty demos/ must disable GC"


def test_sweep_runs_once_per_process(sweep_env):
    """Second call is a no-op (module-level flag)."""
    cache, demos_dir, demo_hash = sweep_env
    demos_dir.mkdir(parents=True, exist_ok=True)
    (demos_dir / "x.dem").write_bytes(b"x" * 64)
    _run_sweep()
    assert not (cache.cache_dir / demo_hash).exists()
    # recreate the orphan; the flag now blocks a second sweep
    (cache.cache_dir / demo_hash).mkdir()
    _run_sweep()
    assert (cache.cache_dir / demo_hash).exists(), "sweep must not re-run"


# ---------- S3: analysis correctness ----------

def _run_funlab(events):
    from cs_analyzer.analysis import AnalysisRunner
    from cs_analyzer.config import AnalysisConfig

    demo = build_parsed_demo(events=events)
    return AnalysisRunner(AnalysisConfig(enabled_modules=["funlab"])).run_one(demo, "funlab")


def test_vulture_requires_same_life_soften():
    """抢人头 must ignore damage from EARLIER lives (S3 P0-1).

    Round 1: Alice is softened by Carol (100->20) and killed by Bob —
    vulture. Round 2: Alice (alive again) is finished by Bob at 20 HP with
    NO soften in that life — not a vulture even though Carol damaged her
    back in round 1.
    """
    import pandas as pd

    from tests.conftest import S_ALICE, S_BOB, S_CAROL

    deaths = pd.DataFrame({
        "tick": [600, 700, 1600, 1700],
        "attacker_steamid": [S_BOB, S_CAROL, S_BOB, S_BOB],
        "user_steamid": [S_ALICE, S_BOB, S_ALICE, S_BOB],
        "attacker_name": ["Bob", "Carol", "Bob", "Bob"],
        "user_steamid": [S_ALICE, S_BOB, S_ALICE, S_BOB],
        "user_name": ["Alice", "Bob", "Alice", "Bob"],
        "assister_steamid": ["", "", "", ""],
        "weapon": ["ak47"] * 4,
        "penetrated": [False] * 4, "thrusmoke": [False] * 4,
        "noscope": [False] * 4, "attackerblind": [False] * 4,
        "attackerinair": [False] * 4,
        "dmg_health": [80.0, 70.0, 20.0, 30.0],
        "user_health": [20.0, 70.0, 20.0, 70.0],
    })
    hurts = pd.DataFrame({
        # round 1: Carol softens Alice (100->20), Bob finishes
        "tick": [400, 500, 600, 700, 1500, 1600, 1700],
        "attacker_steamid": [S_CAROL, S_BOB, S_BOB, S_CAROL,
                             S_ALICE, S_BOB, S_BOB],
        "user_steamid": [S_ALICE, S_ALICE, S_ALICE, S_BOB,
                         S_BOB, S_ALICE, S_BOB],
        "attacker_name": ["Carol", "Bob", "Bob", "Carol",
                          "Alice", "Bob", "Bob"],
        "user_name": ["Alice", "Alice", "Alice", "Bob",
                      "Bob", "Alice", "Bob"],
        "dmg_health": [80.0, 20.0, 0.0, 30.0, 30.0, 20.0, 0.0],
        "user_health": [100.0, 20.0, 20.0, 70.0, 70.0, 20.0, 20.0],
        "health": [20.0, 0.0, 20.0, 40.0, 40.0, 0.0, 20.0],
    })
    r = _run_funlab({"player_hurt": hurts, "player_death": deaths})
    bob = next(p for p in r.players if p["name"] == "Bob")
    # Alice died at 20 HP twice; only the round-1 death had an in-life soften
    assert bob["snipe_kills"] == 1, (
        "round-2 finish had no in-life soften: cross-life damage must not count")


def test_norm_weapon_5e_and_skin_variants():
    """canonical resolves 5E decorated names + WMPVP skins (S3 P0-2)."""
    from cs_analyzer.analysis.weapons import canonical

    cases = {
        "5e_2023pass3_ak47": "ak47",
        "5e_fazesr2026004_usp_silencer": "usp",
        "5ExTEAMSPIRIT_glock": "glock",
        "5e_2023pass3_m4a1_silencer": "m4a1_silencer",
        "5e_2023pass3_ak47_ace": "ak47",
        "awp_txz03": "awp",
        "m4a1_silencer_vip": "m4a1_silencer",
        "ak47_vip": "ak47",
        "Tec-9": "tec9",           # purchase display name
        "MAC-10": "mac10",
        "CZ75-Auto": "cz75a",
        "USP-S": "usp",
        "R8 Revolver": "revolver",
        "Dual Berettas": "elite",
        "P2000": "p2000",
        "Kevlar & Helmet": "kevlarhelmet",
        "Desert Eagle": "deagle",
    }
    for raw, want in cases.items():
        assert canonical(raw) == want, f"canonical({raw!r}) != {want!r}"


def test_drop_profit_round_scoped():
    """发枪成材率 counts only same-round kills (S3: round boundary)."""
    import pandas as pd

    from tests.conftest import S_ALICE, S_BOB, S_CAROL, build_parsed_demo

    # Bob buys ak47 round 1 (tick 10); Alice picks it up (tick 500, Bob
    # alive so it counts as a drop); Alice's ak47 kill happens in ROUND 2
    # (tick 3000) — must NOT credit the drop as profitable.
    purchases = pd.DataFrame({
        "tick": [10, 20, 30],
        "steamid": [S_BOB, S_ALICE, S_CAROL],
        "item_name": ["AK-47", "glock", "glock"],
        "cost": [2700, 0, 0],
    })
    pickups = pd.DataFrame({
        "tick": [500],
        "user_steamid": [S_ALICE],
        "user_name": ["Alice"],
        "item": ["ak47"],
    })
    deaths = pd.DataFrame({
        # round 1: no relevant deaths; round 2: Alice kills Carol WITH ak47
        "tick": [600, 3000],
        "attacker_steamid": [S_BOB, S_ALICE],
        "user_steamid": [S_CAROL, S_BOB],
        "user_name": ["Carol", "Bob"],
        "weapon": ["ak47", "ak47"],
    })
    demo = build_parsed_demo(events={
        "item_purchase": purchases, "item_pickup": pickups,
        "player_death": deaths,
    })
    from cs_analyzer.analysis import AnalysisRunner
    from cs_analyzer.config import AnalysisConfig

    r = AnalysisRunner(AnalysisConfig(enabled_modules=["funlab"])).run_one(demo, "funlab")
    alice = next(p for p in r.players if p["name"] == "Alice")
    bob = next(p for p in r.players if p["name"] == "Bob")
    assert alice["drops_received"] == 1, "pickup with no self-buy = received drop"
    assert bob["drops_profitable"] == 0, "round-2 kill must not credit round-1 drop"


# ---------- S5: engineering gaps ----------

def test_cli_subcommands_help():
    """cli.py had zero coverage — smoke every subcommand's --help exit."""
    from typer.testing import CliRunner

    from cs_analyzer.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("parse", "analyze", "coverage", "serve", "info"):
        r = runner.invoke(app, [cmd, "--help"])
        assert r.exit_code == 0, f"{cmd} --help failed: {r.output}"


def test_maps_loader_missing_map_falls_back():
    """maps/loader.py: a map without PNG+yaml falls back to a blank canvas
    (load_map raises FileNotFoundError; load_map_or_fallback synthesizes)."""
    import pytest as _pytest

    from cs_analyzer.maps.loader import load_map, load_map_or_fallback

    with _pytest.raises(FileNotFoundError):
        load_map("de_this_map_does_not_exist")
    res = load_map_or_fallback("de_this_map_does_not_exist")
    assert res is not None
    assert res.image_width > 0 and res.image_height > 0


def test_warmup_error_path_sets_error_phase(monkeypatch):
    """warmup failure branch: a crashing step lands phase='error' (the
    dashboard JS relies on this to leave the skeleton instead of polling
    forever)."""
    from cs_analyzer.web import snapshots, warmup

    warmup.reset_for_tests()
    # hermetic: no real snapshot reads (a disk hit would skip the stubbed
    # step and the error path would never trigger)
    monkeypatch.setattr(snapshots, "restore_all", lambda out_dir, cache_dir: [])
    monkeypatch.setattr(snapshots, "save_all", lambda out_dir, cache_dir: {})
    monkeypatch.setattr(warmup, "_step_aggregate",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    warmup.start_once()
    deadline = __import__("time").monotonic() + 10
    while warmup.status()["phase"] not in ("error",) and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.05)
    st = warmup.status()
    assert st["phase"] == "error" and "boom" in st["error"]
    warmup.reset_for_tests()


def test_warmup_kick_rearms_after_ready(monkeypatch):
    """kick() resets readiness and re-runs prewarm to completion. All steps
    are stubbed — a REAL kick here would scan the whole library in-process
    and stall the suite."""
    import time as _t

    from cs_analyzer.web import snapshots, warmup

    warmup.reset_for_tests()
    monkeypatch.setattr(snapshots, "restore_all", lambda out_dir, cache_dir: [])
    monkeypatch.setattr(snapshots, "save_all", lambda out_dir, cache_dir: {})
    # EVERY step must be stubbed (S3 lesson): the wave2 shard steps silently
    # depended on disk shards matching the old src8 — a fingerprint-source
    # change made them cold and a real kick scanned the whole library here.
    for name in ("_step_aggregate", "_step_highlights", "_step_teamplay",
                 "_step_utilitylab", "_step_funlab", "_step_map",
                 "_step_lineups", "_step_stylemap", "_step_rating21",
                 "_step_winloo", "_step_aimsci", "_step_lossattr",
                 "_step_evcells", "_step_duelmo"):
        monkeypatch.setattr(warmup, name, lambda: None)
    warmup.kick()
    deadline = _t.monotonic() + 10
    while warmup.status()["phase"] not in ("done",) and _t.monotonic() < deadline:
        _t.sleep(0.02)
    assert warmup.status()["ready"] is True
    warmup.reset_for_tests()
