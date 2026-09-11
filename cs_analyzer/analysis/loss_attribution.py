"""Loss attribution (失利归因, Phase R5): WHY a lost round was lost.

Every lost round gets a set of structured tags (multi-label — one round can
be several kinds of lost):

- lost_opening   掉首口: the round's first kill went to the enemy.
- untraded       无贸易死: >=2 deaths happened within TRADE_WINDOW_TICKS
                 of each other without a teammate killing the killer in
                 between (uses ratings.TRADE_WINDOW_TICKS — single source).
- lost_force     强起失利 / lost_eco    eco 失利: the LOSING side's buy state
                 (economy thresholds — single source via economy module).
- utility_deficit 道具劣势: enemy utility damage (flash-adjusted blind
                 seconds are not additive across teams, so we count HE/
                 molotov/inferno damage) net difference > 1.5x in the
                 enemy's favor with a 20-damage floor.
- lost_clutch    残局失守: the losing side reached a last-man-standing
                 situation (1vX) and still lost (highlights clutch
                 definition, mirrored for losers).

Pure event derivation, no per-tick scanning. Per-demo output: per-round
tag lists + per-team counts, ready for cross-library aggregation at the
web layer.
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.ratings import TRADE_WINDOW_TICKS
from cs_analyzer.analysis.util import clean_sid, round_player_sides
from cs_analyzer.model.parsed_demo import ParsedDemo

UTILITY_FLOOR = 20      # min enemy utility damage for the deficit tag
UTILITY_RATIO = 1.5     # enemy/mine utility damage ratio for the deficit tag


class LossAttributionResult(AnalysisResult):
    rounds: list[dict] = Field(default_factory=list)
    # [{round, winner_side, loser_side, buy, tags:[...], loser_sids:[...]}]
    teams: list[dict] = Field(default_factory=list)
    # [{team, lost_rounds, tags:{tag: count}}] (team = "Team 2"/"Team 3")
    # C2-H2: per-player death granularity in LOST rounds (rate vs presence)
    players: list[dict] = Field(default_factory=list)
    # [{steamid, lost_deaths, untraded_deaths}]
    roster: dict[str, str] = Field(default_factory=dict)  # sid -> display name
    notes: dict = Field(default_factory=dict)


def _buy_state(rounds_econ: dict, side: str) -> str:
    """'eco' | 'force' | 'full' from the economy module's per-round state."""
    v = rounds_econ.get(side)
    if v in ("eco", "force", "full"):
        return v
    return "unknown"


@register_module
class LossAttributionModule(AnalysisModule):
    name = "loss_attribution"
    requires: tuple[str, ...] = ("economy",)

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        res = LossAttributionResult(module=self.name, demo_hash=demo.metadata.demo_hash)
        deaths = demo.events.get("player_death")
        rounds = [r for r in demo.regular_rounds if not getattr(r, "is_warmup", False)]
        if deaths is None or deaths.empty or not rounds:
            res.notes["skipped"] = "no deaths / rounds"
            return res
        deaths = deaths[(deaths["tick"] >= rounds[0].start_tick)]

        try:
            econ = ctx.require("economy")
            # {round: {"T": buy, "CT": buy}} from the economy module's rows
            buy_state: dict[int, dict[str, str]] = defaultdict(dict)
            for rb in getattr(econ, "rounds", []):
                if rb.side in ("T", "CT"):
                    buy_state[rb.round][rb.side] = rb.buy
        except Exception:  # noqa: BLE001 — economy optional, tags degrade
            buy_state = {}

        side_map = round_player_sides(demo)
        roster = {p.steamid: p.name for p in demo.players}
        team_of: dict[str, str] = {}
        for m in side_map.values():
            for sid, s in m.items():
                team_of.setdefault(sid, f"Team {2 if s == 'T' else 3}")

        # index deaths per round, chronological
        kills_rows = []
        for _, row in deaths.iterrows():
            att = clean_sid(row.get("attacker_steamid", ""))
            vic = clean_sid(row.get("user_steamid", ""))
            if not vic:
                continue
            kills_rows.append((int(row.get("tick", 0) or 0), att, vic,
                               str(row.get("weapon", "") or "")))
        kills_rows.sort()

        # utility damage per side per round (HE + molotov/inferno + fired grenade hurts)
        hurt = demo.events.get("player_hurt")
        util_dmg: dict[tuple[int, str], int] = defaultdict(int)
        if hurt is not None and not hurt.empty:
            h = hurt[hurt["tick"] >= rounds[0].start_tick]
            for _, row in h.iterrows():
                att = clean_sid(row.get("attacker_steamid", ""))
                vic = clean_sid(row.get("user_steamid", ""))
                if not att or not vic or att == vic:
                    continue
                wpn = str(row.get("weapon", "") or "").lower()
                if not any(k in wpn for k in ("hegrenade", "molotov", "inferno", "incgrenade")):
                    continue
                rnd_h = self._round_of(rounds, int(row["tick"]))
                if rnd_h is None:
                    continue
                s = side_map.get(rnd_h.number, {}).get(att, "")
                if s:
                    util_dmg[(rnd_h.number, s)] += int(row.get("dmg_health", 0) or 0)

        # clutch losers: last-alive moment of the LOSING side while the WINNING
        # side still had >=2 alive (highlights' 1vX definition, mirrored for
        # the loser) — and the loser still lost the round.
        clutch_loser_rounds: set[int] = set()
        for rnd in rounds:
            window = [k for k in kills_rows
                      if rnd.start_tick <= k[0] < rnd.end_tick]
            if not window or not rnd.winner_side:
                continue
            loser = "CT" if rnd.winner_side == "T" else "T"
            smap = side_map.get(rnd.number, {})
            loser_alive = {sid for sid, s in smap.items() if s == loser}
            enemy_alive = {sid for sid, s in smap.items() if s != loser}
            for t, att, vic, _w in window:
                loser_alive.discard(vic)
                enemy_alive.discard(att if smap.get(att, "") and
                                    smap.get(att, "") != loser else "")
                if len(loser_alive) == 1:
                    if len({s for s in enemy_alive if s}) >= 2:
                        clutch_loser_rounds.add(rnd.number)
                    break

        teams_counts: dict[str, dict] = {}
        player_stats: dict[str, list] = {}  # C2-H2: sid -> [lost_deaths, untraded]
        for rnd in rounds:
            if not rnd.winner_side:
                continue
            loser = "CT" if rnd.winner_side == "T" else "T"
            window = [k for k in kills_rows
                      if rnd.start_tick <= k[0] < rnd.end_tick]
            tags: list[str] = []

            smap = side_map.get(rnd.number, {})
            losers = [sid for sid, s in smap.items() if s == loser]
            if not losers:
                continue

            # 1. lost opening
            first = next((k for k in window if k[1] and k[2]), None)
            if first and smap.get(first[2], "") == loser and smap.get(first[1], "") == rnd.winner_side:
                tags.append("lost_opening")

            # 2. untraded deaths: count loser deaths whose killer was NOT
            #    killed by a loser-side teammate within TRADE_WINDOW_TICKS.
            #    Tag when >=2 such deaths (a single untraded death is normal).
            #    C2-H2: also accumulated per VICTIM for the rate metric.
            untraded = 0
            loser_deaths = [k for k in window
                            if smap.get(k[2], "") == loser and k[1]]
            for t0, killer, vic, _w in loser_deaths:
                traded = any(
                    t0 < t <= t0 + TRADE_WINDOW_TICKS
                    and a and v == killer and smap.get(a, "") == loser
                    for t, a, v, _w2 in window
                )
                pst = player_stats.setdefault(vic, [0, 0])
                pst[0] += 1
                if not traded:
                    untraded += 1
                    pst[1] += 1
            if untraded >= 2:
                tags.append("untraded")

            # 3/4. buy state of the loser side
            buy = _buy_state(buy_state.get(rnd.number, {}), loser)
            if buy == "force":
                tags.append("lost_force")
            elif buy == "eco":
                tags.append("lost_eco")

            # 5. utility deficit
            mine = util_dmg.get((rnd.number, loser), 0)
            theirs = util_dmg.get((rnd.number, rnd.winner_side), 0)
            if theirs > UTILITY_FLOOR and theirs > UTILITY_RATIO * mine:
                tags.append("utility_deficit")

            # 6. clutch lost
            if rnd.number in clutch_loser_rounds:
                tags.append("lost_clutch")

            res.rounds.append({
                "round": rnd.number, "winner_side": rnd.winner_side,
                "loser_side": loser, "buy": buy, "tags": tags,
                "loser_sids": sorted(losers),
                "t_score": rnd.t_score, "ct_score": rnd.ct_score,
            })

            team = next((team_of[sid] for sid in losers if sid in team_of), None)
            if team:
                tc = teams_counts.setdefault(
                    team, {"team": team, "lost_rounds": 0, "tags": defaultdict(int)})
                tc["lost_rounds"] += 1
                for tag in tags:
                    tc["tags"][tag] += 1

        res.teams = [
            {"team": tc["team"], "lost_rounds": tc["lost_rounds"],
             "tags": dict(sorted(tc["tags"].items(), key=lambda kv: -kv[1]))}
            for tc in teams_counts.values()
        ]
        res.players = [
            {"steamid": sid, "lost_deaths": d, "untraded_deaths": u}
            for sid, (d, u) in sorted(player_stats.items())
        ]
        res.roster = roster
        return res

    @staticmethod
    def _round_of(rounds, tick: int):
        import bisect as _b
        starts = [r.start_tick for r in rounds]
        i = _b.bisect_right(starts, tick) - 1
        return rounds[i] if i >= 0 else None
