"""Phase R tests: statistical rigor retrofit + aim science + utility execution
science + loss attribution + research web APIs/shards."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cs_analyzer.analysis.aim_science import compute_aim_science
from cs_analyzer.analysis.runner import AnalysisRunner
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import DemoData, MatchMetadata, ProviderKind, Team
from tests.conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE, make_player, make_round

T_ALICE = {"tick": 0, "steamid": S_ALICE}  # readability helper below


def _aim_demo() -> ParsedDemo:
    """Two players, two engagements with KNOWN geometry (yaw conventions).

    Carol (T) at (0,0); Alice (CT) at (0,-1000). +y is "south" in this
    synthetic world. Under the Source convention (forward = (cp·cy, cp·sy,
    −sp)) yaw 270 faces (0,-1) — exactly toward Alice from Carol; yaw 240
    is a 30° offset. The calibration diagnostic (aim at damage) must read
    ~0°, preaim must read 30°.
    """
    team_a = Team(name="Team 3", starting_side="CT")
    team_b = Team(name="Team 2", starting_side="T")
    players = [
        make_player(S_ALICE, "Alice", "Team 3"),
        make_player(S_CAROL, "Carol", "Team 2"),
    ]
    rounds = [
        make_round(1, 0, 2560, "CT", winner="Team 3", ct_score=1),
        make_round(2, 2560, 5120, "T", winner="Team 2", t_score=1),
    ]
    metadata = MatchMetadata(
        map_name="de_mirage", demo_path="aim.dem", demo_hash="aimhash1",
        provider=ProviderKind.UNKNOWN, team_a=team_a, team_b=team_b,
    )

    def row(sid, tick, x, y, yaw, vel=0.0):
        return {"steamid": sid, "tick": tick, "X": float(x), "Y": float(y),
                "Z": 0.0, "pitch": 0.0, "yaw": float(yaw),
                "velocity": vel, "is_alive": True, "team_num": 2.0 if sid == S_CAROL else 3.0}

    ticks = pd.DataFrame([
        # side-resolution window for round_player_sides (start..start+512)
        row(S_ALICE, 0, 0, -1000, 90), row(S_ALICE, 256, 0, -1000, 90),
        row(S_CAROL, 0, 0, 0, 270), row(S_CAROL, 256, 0, 0, 270),
        # engagement 1: Carol hurts Alice @1300 (preaim sample @1276 = 30° off)
        row(S_CAROL, 1276, 0, 0, 240), row(S_CAROL, 1300, 0, 0, 270),
        row(S_ALICE, 1276, 0, -1000, 90), row(S_ALICE, 1300, 0, -1000, 90),
        # Alice counter-shots @1316 (0.25s latency)
        row(S_ALICE, 1316, 0, -1000, 90, vel=0.0),
        # engagement 2: Alice hurts Carol @1400 (preaim @1376 = 30° off)
        row(S_ALICE, 1376, 0, -1000, 60), row(S_ALICE, 1400, 0, -1000, 90, vel=100.0),
        row(S_CAROL, 1400, 0, 0, 270, vel=0.0),
        # Carol counter-shots @1432 (0.5s latency)
        row(S_CAROL, 1432, 0, 0, 270, vel=0.0),
    ])
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1300, 1400],
            "attacker_steamid": [S_CAROL, S_ALICE],
            "user_steamid": [S_ALICE, S_CAROL],
            "attacker_name": ["Carol", "Alice"],
            "user_name": ["Alice", "Carol"],
            "dmg_health": [30, 25],
            "weapon": ["ak47", "ak47"],
        }),
        "weapon_fire": pd.DataFrame({
            "tick": [1300, 1316, 1432],
            "user_steamid": [S_CAROL, S_ALICE, S_CAROL],
            "user_name": ["Carol", "Alice", "Carol"],
            "weapon": ["ak47", "ak47", "ak47"],
        }),
        "player_death": pd.DataFrame({
            "tick": [1500, 2000],
            "attacker_steamid": [S_CAROL, S_ALICE],
            "user_steamid": [S_ALICE, S_CAROL],
            "attacker_name": ["Carol", "Alice"],
            "user_name": ["Alice", "Carol"],
            "weapon": ["ak47", "ak47"],
        }),
    }
    return ParsedDemo(data=DemoData(metadata=metadata, players=players, rounds=rounds),
                      events=events, ticks=ticks)


class TestAimScience:
    def test_preaim_counter_streak_geometry(self):
        res = compute_aim_science(_aim_demo())
        assert res.players, "module must produce players"
        by_sid = {p["steamid"]: p for p in res.players}
        carol = by_sid[S_CAROL]
        alice = by_sid[S_ALICE]
        # preaim: sampled 24 ticks before first damage — 30° off dead-on
        assert carol["preaim_med_deg"] == pytest.approx(30.0, abs=0.5)
        assert alice["preaim_med_deg"] == pytest.approx(30.0, abs=0.5)
        # calibration diagnostic: aim at the damage event ≈ dead-on
        assert carol["aim_dmg_med_deg"] == pytest.approx(0.0, abs=1.0)
        # counter-shot latency: Alice 16 ticks (0.25s), Carol 32 ticks (0.5s)
        assert alice["counter_med_s"] == pytest.approx(0.25, abs=0.02)
        assert carol["counter_med_s"] == pytest.approx(0.5, abs=0.02)
        assert alice["counter_fast_rate"] == 1.0  # ≤0.5s counts as fast
        # shot → damage: Carol's fire @1300 matches her hurt @1300
        assert carol["fire_damage_rate"] == pytest.approx(0.5, abs=0.01)
        # movement buckets at engagement: Carol stopped, Alice moving
        assert carol["duel_stopped_n"] == 1 and carol["duel_stopped_wins"] == 1
        assert alice["duel_moving_n"] == 1 and alice["duel_moving_wins"] == 0

    def test_missing_tick_columns_degrades(self):
        demo = _aim_demo()
        demo.ticks = demo.ticks[["steamid", "tick"]]
        res = compute_aim_science(demo)
        assert res.players == [] and "skipped" in res.notes


def _loss_demo() -> ParsedDemo:
    team_a = Team(name="Team 3", starting_side="CT")
    team_b = Team(name="Team 2", starting_side="T")
    players = [
        make_player(S_ALICE, "Alice", "Team 3"),
        make_player(S_BOB, "Bob", "Team 3"),
        make_player(S_CAROL, "Carol", "Team 2"),
        make_player(S_DAVE, "Dave", "Team 2"),
    ]
    rounds = [
        make_round(1, 0, 2560, "CT", winner="Team 3", ct_score=1),
        make_round(2, 2560, 5120, "T", winner="Team 2", t_score=1),
    ]
    metadata = MatchMetadata(
        map_name="de_mirage", demo_path="loss.dem", demo_hash="losshash1",
        provider=ProviderKind.UNKNOWN, team_a=team_a, team_b=team_b,
    )

    def side_rows(tick, t_num):
        return [{"steamid": sid, "tick": tick, "X": 0.0, "Y": 0.0,
                 "team_num": t_num[sid]} for sid in t_num]

    t_num = {S_ALICE: 3.0, S_BOB: 3.0, S_CAROL: 2.0, S_DAVE: 2.0}
    ticks = pd.DataFrame(
        side_rows(0, t_num) + side_rows(256, t_num)
        + side_rows(2600, {S_ALICE: 3.0, S_BOB: 3.0, S_CAROL: 2.0, S_DAVE: 2.0})
    )
    events = {
        "player_death": pd.DataFrame({
            # r1: T loses both quickly, no trade
            "tick": [600, 700, 2800, 2900],
            "attacker_steamid": [S_ALICE, S_BOB, S_CAROL, S_CAROL],
            "user_steamid": [S_CAROL, S_DAVE, S_BOB, S_ALICE],
            "attacker_name": ["Alice", "Bob", "Carol", "Carol"],
            "user_name": ["Carol", "Dave", "Bob", "Alice"],
            "weapon": ["ak47"] * 4,
        }),
        "item_purchase": pd.DataFrame({
            # r1 T-side eco spend (500 avg); r2 CT-side force (3000 avg)
            "tick": [100, 100, 2600, 2600],
            "steamid": [S_CAROL, S_DAVE, S_ALICE, S_BOB],
            "item_name": ["ak47"] * 4,
            "cost": [500, 500, 3000, 3000],
        }),
    }
    return ParsedDemo(data=DemoData(metadata=metadata, players=players, rounds=rounds),
                      events=events, ticks=ticks)


class TestLossAttribution:
    def test_tags_per_round(self):
        demo = _loss_demo()
        res = AnalysisRunner().run_one(demo, "loss_attribution")
        by_round = {r["round"]: r for r in res.rounds}
        r1, r2 = by_round[1], by_round[2]
        assert r1["loser_side"] == "T" and r1["buy"] == "eco"
        # both rounds end 1v1 -> enemy has <2 alive -> NOT a clutch (R rule)
        assert set(r1["tags"]) == {"lost_opening", "untraded", "lost_eco"}
        assert r2["loser_side"] == "CT" and r2["buy"] == "force"
        assert set(r2["tags"]) == {"lost_opening", "untraded", "lost_force"}
        assert set(r1["loser_sids"]) == {S_CAROL, S_DAVE}
        assert set(r2["loser_sids"]) == {S_ALICE, S_BOB}
        teams = {t["team"]: t for t in res.teams}
        assert teams["Team 2"]["lost_rounds"] == 1
        assert teams["Team 2"]["tags"]["untraded"] == 1

    def test_trade_within_window_kills_tag(self):
        demo = _loss_demo()
        # Bob avenges Carol within the 128-tick trade window -> no untraded tag
        deaths = demo.events["player_death"]
        extra = pd.DataFrame({
            "tick": [620],
            "attacker_steamid": [S_DAVE],
            "user_steamid": [S_ALICE],
            "attacker_name": ["Dave"],
            "user_name": ["Alice"],
            "weapon": ["ak47"],
        })
        demo.events["player_death"] = pd.concat([deaths, extra], ignore_index=True)
        res = AnalysisRunner().run_one(demo, "loss_attribution")
        r1 = next(r for r in res.rounds if r["round"] == 1)
        assert "untraded" not in r1["tags"]

    def test_player_untraded_counts_c2h2(self):
        """C2-H2: per-player untraded granularity in LOST rounds."""
        demo = _loss_demo()
        res = AnalysisRunner().run_one(demo, "loss_attribution")
        by_sid = {p["steamid"]: p for p in res.players}
        # R1 T loses (Carol, Dave die unavenged); R2 CT loses (Bob, Alice die
        # unavenged — per the R2 tags). One lost death each, all untraded.
        assert by_sid[S_CAROL] == {"steamid": S_CAROL, "lost_deaths": 1,
                                   "untraded_deaths": 1}
        assert by_sid[S_DAVE]["untraded_deaths"] == 1
        assert by_sid[S_ALICE]["lost_deaths"] == 1
        assert by_sid[S_BOB]["untraded_deaths"] == 1
        assert set(by_sid) == {S_ALICE, S_BOB, S_CAROL, S_DAVE}

    def test_player_traded_death_not_counted_c2h2(self):
        demo = _loss_demo()
        deaths = demo.events["player_death"]
        extra = pd.DataFrame({
            "tick": [620],
            "attacker_steamid": [S_DAVE],
            "user_steamid": [S_ALICE],
            "attacker_name": ["Dave"],
            "user_name": ["Alice"],
            "weapon": ["ak47"],
        })
        demo.events["player_death"] = pd.concat([deaths, extra], ignore_index=True)
        res = AnalysisRunner().run_one(demo, "loss_attribution")
        by_sid = {p["steamid"]: p for p in res.players}
        assert by_sid[S_CAROL]["lost_deaths"] == 1
        assert by_sid[S_CAROL]["untraded_deaths"] == 0  # traded by Dave
        assert by_sid[S_DAVE]["untraded_deaths"] == 1


def _utility_demo() -> ParsedDemo:
    team_a = Team(name="Team 3", starting_side="CT")
    team_b = Team(name="Team 2", starting_side="T")
    players = [
        make_player(S_ALICE, "Alice", "Team 3"),
        make_player(S_BOB, "Bob", "Team 3"),
        make_player(S_CAROL, "Carol", "Team 2"),
        make_player(S_DAVE, "Dave", "Team 2"),
    ]
    rounds = [make_round(1, 0, 2560, "T", winner="Team 2", t_score=1)]
    metadata = MatchMetadata(
        map_name="de_mirage", demo_path="util.dem", demo_hash="utilhash1",
        provider=ProviderKind.UNKNOWN, team_a=team_a, team_b=team_b,
    )

    def side_row(sid, tick):
        return {"steamid": sid, "tick": tick, "X": 0.0, "Y": 0.0,
                "team_num": 2.0 if sid in (S_CAROL, S_DAVE) else 3.0}

    ticks = pd.DataFrame([side_row(sid, t)
                          for t in (0, 256, 512)
                          for sid in (S_ALICE, S_BOB, S_CAROL, S_DAVE)])
    events = {
        "flashbang_detonate": pd.DataFrame({
            "tick": [600], "user_steamid": [S_CAROL], "user_name": ["Carol"],
            "x": [10.0], "y": [10.0],
        }),
        "player_blind": pd.DataFrame({
            "tick": [600], "user_steamid": [S_ALICE], "user_name": ["Alice"],
            "blind_duration": [2.0],
        }),
        "smokegrenade_detonate": pd.DataFrame({
            "tick": [690, 1100], "user_steamid": [S_CAROL, S_CAROL],
            "user_name": ["Carol", "Carol"], "x": [1.0, 2.0], "y": [1.0, 2.0],
        }),
        "molotov_detonate": pd.DataFrame({
            "tick": [650], "user_steamid": [S_DAVE], "user_name": ["Dave"],
        }),
        "player_hurt": pd.DataFrame({
            "tick": [700, 1000],
            "attacker_steamid": [S_DAVE, S_DAVE],
            "user_steamid": [S_ALICE, S_BOB],
            "attacker_name": ["Dave", "Dave"],
            "user_name": ["Alice", "Bob"],
            "weapon": ["ak47", "inferno"],
            "dmg_health": [100, 30],
        }),
        "player_death": pd.DataFrame({
            "tick": [700],
            "attacker_steamid": [S_DAVE],
            "user_steamid": [S_ALICE],
            "attacker_name": ["Dave"],
            "user_name": ["Alice"],
            "weapon": ["ak47"],
        }),
    }
    return ParsedDemo(data=DemoData(metadata=metadata, players=players, rounds=rounds),
                      events=events, ticks=ticks)


class TestUtilityExecScience:
    def test_support_flash_late_molly(self):
        demo = _utility_demo()
        res = AnalysisRunner().run_one(demo, "utility_effect")
        by_sid = {p["steamid"]: p for p in res.exec_players}
        carol = by_sid[S_CAROL]
        dave = by_sid[S_DAVE]
        # support flash: blinded Alice @600, teammate Dave killed her @700
        assert carol["enemy_blind_throws"] == 1
        assert carol["support_kills"] == 1
        assert carol["support_flash_rate"] == 1.0
        # throws: 1 flash + 2 smokes = 3; smoke @1100 is late (anchor @700)
        assert carol["throws"] == 3 and carol["late_throws"] == 1
        assert carol["late_rate"] == pytest.approx(1 / 3, abs=0.01)
        # molly: one throw, 30 fire damage
        assert dave["molly_throws"] == 1
        assert dave["molly_dmg_per_throw"] == pytest.approx(30.0, abs=0.1)
        # smoke-before-contact buckets: T side 1 smoke before anchor @700
        t_round = next(r for r in res.exec_rounds if r["side"] == "T")
        assert t_round["smokes"] == 1 and t_round["won"] == 1


@pytest.fixture
def research_client(tmp_path, monkeypatch):
    """web_client variant backed by the aim-science synthetic demo."""
    from fastapi.testclient import TestClient

    from cs_analyzer.cache import DemoCache
    from cs_analyzer.config import Settings
    from cs_analyzer.web import aggregation, app as web_app

    demo = _aim_demo()
    cache = DemoCache(tmp_path / "cache")
    cache.save(demo.metadata.demo_hash, demo)
    monkeypatch.setattr(web_app, "_cache", lambda: cache)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")
    monkeypatch.setattr(web_app, "_demos_dir", lambda: tmp_path / "demos")
    monkeypatch.setattr(web_app, "_settings", lambda: Settings())
    aggregation.invalidate_aggregate()
    return TestClient(web_app.app), demo.metadata.demo_hash


class TestResearchWeb:
    def test_aim_science_api_and_shards(self, research_client, tmp_path):
        client, demo_hash = research_client
        # S3-B2: the cross-library route is peek-only — cold memo -> 503
        assert client.get("/api/aim-science.json").status_code == 503
        # report-level access warms the shard memo (documented contract);
        # on the 1-demo synthetic library this is fast.
        from cs_analyzer.web import aim_data

        aim_data.invalidate_aimsci()
        body_warm = aim_data.aim_report()
        assert body_warm["players"]
        r = client.get("/api/aim-science.json")
        assert r.status_code == 200
        body = r.json()
        carol = next(p for p in body["players"] if p["steamid"] == S_CAROL)
        assert carol["preaim_med_deg"] == pytest.approx(30.0, abs=0.5)
        assert carol["preaim_lt10_conf"]["gated"] is True  # n=1 < 20
        assert body["notes"]["boundaries"]
        # shards persisted on disk (shards/<memo>/<src8>/<hash>_<model8>.json)
        shards = list((tmp_path / "web" / "snapshots" / "shards" / "aimsci")
                      .rglob("*.json"))
        assert shards, "aimsci shard family must be written"

    def test_loss_patterns_api_and_shards(self, research_client, tmp_path):
        client, demo_hash = research_client
        # Carol's side (Team 2) loses round 1 of the synthetic demo
        # S3-B2: peek-only route — cold memo -> 503, warm explicitly first
        assert client.get(
            f"/api/loss-patterns.json?player={S_CAROL}").status_code == 503
        from cs_analyzer.web import loss_data

        loss_data.invalidate_lossattr()
        assert loss_data.loss_report()["teams"] is not None
        r = client.get(f"/api/loss-patterns.json?player={S_CAROL}")
        assert r.status_code == 200
        body = r.json()
        assert body["lost_rounds"] >= 0 and "tag_defs" in body
        # a player whose side never lost -> 404 (honest empty, not fake zeros)
        assert client.get(f"/api/loss-patterns.json?player={S_ALICE}").status_code == 404
        r0 = client.get("/api/loss-patterns.json")
        assert r0.status_code == 200 and "teams" in r0.json()
        shards = list((tmp_path / "web" / "snapshots" / "shards" / "lossattr")
                      .rglob("*.json"))
        assert shards, "lossattr shard family must be written"
        # demo route shape (live endpoint: the match page loss chips consume it)
        r2 = client.get(f"/api/demo/{demo_hash}/loss-attribution.json")
        assert r2.status_code == 200
        assert "rounds" in r2.json() and "teams" in r2.json()

    def test_dead_research_routes_stay_dead(self, web_client):
        """S3-C: the two orphaned per-demo endpoints (zero UI consumers since
        birth) are removed — locked at the source level like test_phase_s2
        A3 so they cannot quietly return."""
        src = Path("cs_analyzer/web/app.py").read_text(encoding="utf-8")
        assert '"/api/demo/{demo_hash}/analysis/aim_science.json"' not in src
        assert '"/api/demo/{demo_hash}/analysis/economy_ev.json"' not in src
        # and the API surface agrees
        client, demo_hash, _demo = web_client
        assert client.get(
            f"/api/demo/{demo_hash}/analysis/aim_science.json").status_code == 404
        assert client.get(
            f"/api/demo/{demo_hash}/analysis/economy_ev.json").status_code == 404

    def test_career_conf_api(self, web_client):
        client, demo_hash, demo = web_client
        r = client.get(f"/api/player/{S_ALICE}/career-conf.json")
        assert r.status_code == 200
        body = r.json()
        for key in ("rating", "kast", "adr", "kpr"):
            assert body[key]["n"] > 0
            assert body[key]["lo"] <= body[key]["hi"]
            assert "shrunk" in body[key]
        assert body["hs"]["n"] > 0
        # S3-D3: hs is a Wilson interval (proportion) — no EB shrinkage by
        # design; lock the contract so the vacuous `or True` never returns.
        assert "shrunk" not in body["hs"]
