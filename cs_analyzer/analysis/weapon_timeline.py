"""Weapon hold timeline (Phase U2 武器持有时间线).

From the cached per-tick ``active_weapon_name`` column, derive per player:
- hold segments: (weapon, round, start_tick, end_tick) runs of the same
  equipped weapon (switches only; reloads/deaths split naturally because
  ``is_alive`` gates the run)
- hold-time aggregation per weapon class (rifle / sniper / pistol / smg /
  heavy / knife / grenade / utility-check) with per-round normalization
- round-start equip: what the player carried when the freeze ended (the
  buy-round fingerprint that feeds the eco timeline)

Everything derives from ticks already in the parse cache — no
PARSER_VERSION bump. Weapon classification reuses analysis.weapons.
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.util import clean_sid
from cs_analyzer.model.parsed_demo import ParsedDemo

MIN_SEGMENT_TICKS = 8  # ~0.125s at 64 tick — noise floor for "equipped"


class WeaponSegment(BaseModel):
    weapon: str
    round: int
    start_tick: int
    end_tick: int


class WeaponHold(BaseModel):
    weapon: str
    ticks: int = 0
    segments: int = 0
    kills: int = 0


class WeaponTimelinePlayer(BaseModel):
    steamid: str
    name: str
    team: str
    holds: list[WeaponHold] = Field(default_factory=list)
    segments: list[WeaponSegment] = Field(default_factory=list)
    round_equips: dict[str, str] = Field(default_factory=dict)  # "1" -> "AK-47"


class WeaponTimelineResult(AnalysisResult):
    players: list[WeaponTimelinePlayer] = Field(default_factory=list)
    rounds_total: int = 0


@register_module
class WeaponTimelineModule(AnalysisModule):
    name = "weapon_timeline"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        rounds = demo.regular_rounds
        ticks = demo.ticks
        kills_df = demo.events.get("player_death")
        out: list[WeaponTimelinePlayer] = []
        if ticks is None or ticks.empty or "active_weapon_name" not in ticks.columns or not rounds:
            return WeaponTimelineResult(module=self.name, demo_hash=demo.metadata.demo_hash)

        # round boundaries for attribution
        bounds = [(r.number, r.start_tick, r.end_tick, r.winner_side) for r in rounds]
        kills_by = defaultdict(int)
        if kills_df is not None and not kills_df.empty and "attacker_steamid" in kills_df.columns:
            from cs_analyzer.analysis.weapons import canonical

            kdf = kills_df[["tick", "attacker_steamid", "weapon"]].copy()
            kdf["attacker_steamid"] = kdf["attacker_steamid"].map(clean_sid)
            kdf["weapon"] = kdf["weapon"].map(canonical)
            for _i, row in kdf.iterrows():
                kills_by[(row["attacker_steamid"], str(row["weapon"]))] += 1

        def round_of(tick: int) -> int:
            for num, start, end, _w in bounds:
                if start <= tick <= end:
                    return num
            return bounds[0][0] if bounds else 0

        # group once by steamid (vectorized sort then python walk per player)
        t = ticks[["tick", "steamid", "name", "team_num", "is_alive", "active_weapon_name"]].copy()
        t["steamid"] = t["steamid"].map(clean_sid)
        from cs_analyzer.analysis.weapons import canonical

        t["active_weapon_name"] = t["active_weapon_name"].map(
            lambda w: canonical(w) if isinstance(w, str) and w else w)
        t = t.sort_values(["steamid", "tick"])

        for sid, g in t.groupby("steamid", sort=False):
            if not sid:
                continue
            g = g.sort_values("tick")  # per-player chronological order
            if g.empty or g["is_alive"].sum() == 0:
                continue
            holds: dict[str, WeaponHold] = {}
            segments: list[WeaponSegment] = []
            round_equips: dict[str, str] = {}
            seen_rounds: set[int] = set()

            cur_weapon = None
            seg_start = 0
            last_tick = 0
            for row in g.itertuples(index=False):
                w = row.active_weapon_name
                if not isinstance(w, str) or not w:
                    w = "unknown"
                tick = int(row.tick)
                if not row.is_alive:
                    # death closes the current hold run (respawn = new segment)
                    if cur_weapon is not None and tick - seg_start >= MIN_SEGMENT_TICKS:
                        rnum = round_of(seg_start)
                        segments.append(WeaponSegment(weapon=cur_weapon, round=rnum,
                                                      start_tick=seg_start, end_tick=tick))
                        h = holds.setdefault(cur_weapon, WeaponHold(weapon=cur_weapon))
                        h.ticks += tick - seg_start
                        h.segments += 1
                    cur_weapon = None
                    last_tick = tick
                    continue
                if cur_weapon is None or w != cur_weapon:
                    if cur_weapon is not None and tick - seg_start >= MIN_SEGMENT_TICKS:
                        rnum = round_of(seg_start)
                        segments.append(WeaponSegment(weapon=cur_weapon, round=rnum,
                                                      start_tick=seg_start, end_tick=last_tick))
                        h = holds.setdefault(cur_weapon, WeaponHold(weapon=cur_weapon))
                        h.ticks += last_tick - seg_start
                        h.segments += 1
                    cur_weapon, seg_start = w, tick
                last_tick = tick
                rnum = round_of(tick)
                if rnum not in seen_rounds:
                    seen_rounds.add(rnum)
                    round_equips[str(rnum)] = w
            # final segment
            if cur_weapon and last_tick - seg_start >= MIN_SEGMENT_TICKS:
                rnum = round_of(seg_start)
                segments.append(WeaponSegment(weapon=cur_weapon, round=rnum,
                                              start_tick=seg_start, end_tick=last_tick))
                h = holds.setdefault(cur_weapon, WeaponHold(weapon=cur_weapon))
                h.ticks += last_tick - seg_start
                h.segments += 1

            for w, h in holds.items():
                h.kills = kills_by.get((sid, w), 0)
            holds_list = sorted(holds.values(), key=lambda x: -x.ticks)
            name = str(g["name"].dropna().iloc[0]) if g["name"].notna().any() else sid
            team_num = g["team_num"].dropna()
            team = "Team 2" if (len(team_num) and team_num.iloc[0] == 2) else "Team 3"
            out.append(WeaponTimelinePlayer(
                steamid=sid, name=name, team=team,
                holds=[h for h in holds_list if h.ticks > 0],
                segments=segments, round_equips=round_equips,
            ))

        return WeaponTimelineResult(
            module=self.name, demo_hash=demo.metadata.demo_hash,
            players=out, rounds_total=len(rounds),
        )
