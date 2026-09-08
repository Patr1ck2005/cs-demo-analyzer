"""Fun/quirky per-player metrics (Phase M 趣味数据实验室, /fun-lab).

Metric definitions are USER-APPROVED in docs/funlab-metrics.md (v2). Key
semantics, all verified against real caches:

- Weapon-drop chain (发枪): no drop events exist, so a drop A->B(w) is
  inferred when teammate B picks up the same primary weapon A bought this
  round, B did not buy it himself (purchases always emit item_pickup rows —
  verified 5/5), A was alive at pickup (no death row for A in [T1,T2]), and
  the buy was within 30s. 314 real drops detected across the 18-demo library.
- Kill-finish attribution (抢人头): player_death.user_health is the victim's
  HP BEFORE the final blow (user_health=pre-hit, health=post-hit — verified).
  A kill counts as 抢人头 when that HP <= VULTURE_HP AND some OTHER teammate
  (same side as the killer) had damaged the victim earlier in that life.
- 被抢人头: the mirror — you damaged a victim below the line and a teammate
  finished them.
- 白给: a whole life dealing <10 damage (user-approved threshold).
- eco特: kills vs enemy-eco rounds (team buy classification reused from the
  economy heuristics). 神仙率 uses per-eco-round opportunities (web memo).
- Fun flags straight from player_death columns (penetrated/thrusmoke/
  noscope/attackerblind/attackerinair/weapon knife|taser) + distance (m).

Per-demo AnalysisModule; web/funlab_data.py merges demos cross-library and
enforces the >=MIN_DEMOS appearance gate before anything is charted.
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from cs_analyzer.analysis.base import AnalysisContext, AnalysisModule, AnalysisResult, register_module
from cs_analyzer.analysis.economy import ECO_MAX, FORCE_MAX, build_purchase_log
from cs_analyzer.analysis.util import clean_sid as _s
from cs_analyzer.analysis.util import round_player_sides
from cs_analyzer.analysis.weapons import canonical as norm_weapon
from cs_analyzer.model.parsed_demo import ParsedDemo

#: HP at or below which a kill counts as 抢人头 (收割线)
VULTURE_HP = 30
#: deaths avenged within this many ticks count as traded
TRADE_WINDOW_TICKS = 128
#: white-give (白给) life threshold: total damage dealt below this = whiff
WHIFF_DMG = 10.0
#: a weapon drop A->B is credited when B picks up within this window
DROP_WINDOW_TICKS = 30 * 64
#: primary weapons eligible for drop accounting (rifles/pistols; not nades/gear)
PRIMARY_WEAPONS = {
    "ak47", "m4a4", "m4a1_silencer", "m4a1", "galilar", "famas", "aug",
    "sg556", "ssg08", "awp", "deagle", "fiveseven", "tec9", "glock",
    "usp_silencer", "p250", "cz75a", "elite", "revolver", "hkp2000",
}
#: 起长枪（叛逆者口径）—— 沙鹰/鸟狙不算（鸟狙=装逼枪，用户裁决 v5）
RIFLE_WEAPONS = {"ak47", "m4a4", "m4a1_silencer", "m4a1", "galilar",
                 "famas", "aug", "sg556", "awp"}
#: 装逼枪（一枪秒人/赌一枪命中 = 花活枪；鸟狙=装逼枪是用户裁决）
SHOWOFF_WEAPONS = {"deagle", "ssg08"}


class FunLabResult(AnalysisResult):
    """Per-player fun metrics for ONE demo (merged cross-demo by the web memo)."""

    players: list[dict] = Field(default_factory=list)
    # per round/side buy class for context: [{round, side, buy}]
    buys: list[dict] = Field(default_factory=list)
    # inferred weapon drops this demo: [{round, donor, receiver, weapon, cost}]
    drops: list[dict] = Field(default_factory=list)


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _flag(v) -> bool:
    return v is True or v == 1 or v == "1" or v == "True"


@register_module
class FunLabModule(AnalysisModule):
    name = "funlab"
    requires: tuple[str, ...] = ()

    def run(self, demo: ParsedDemo, ctx: AnalysisContext) -> AnalysisResult:
        res = FunLabResult(module=self.name, demo_hash=demo.metadata.demo_hash)
        deaths = demo.events.get("player_death")
        hurt = demo.events.get("player_hurt")
        reg = demo.regular_rounds
        if not reg:
            return res
        start_tick = reg[0].start_tick
        side_of = round_player_sides(demo)  # round -> sid -> "T"|"CT"
        players: dict[str, dict] = {}

        def P(sid: str, name: str = "") -> dict:
            p = players.setdefault(sid, {
                "steamid": sid, "name": name or sid,
                "kills": 0, "lives": 0,
                "snipe_kills": 0,     # 抢人头 (assist-softened finishing blow)
                "stolen_from": 0,     # 被抢人头 (you softened, teammate finished)
                "eco_frag_opponent": 0, "eco_frag_self": 0, "eco_rounds_played": 0,
                "team_lost_rounds": 0, "survived_losses": 0, "multi_rounds": 0,
                "rebel_rounds": 0, "rebel_wins": 0, "rebel_kills": 0,
                "showoff_rounds": 0,     # 装逼 (eco局买沙鹰/鸟狙, 未起长枪)
                "pure_eco_rounds": 0,    # 纯eco (eco局消费<500)
                "whiff_lives": 0,
                "traded_deaths": 0, "avenges": 0, "teammate_deaths": 0,
                "wallbang": 0, "thrusmoke": 0, "noscope": 0,
                "blind": 0, "air": 0, "knife": 0, "taser": 0,
                "team_dmg": 0.0, "clutch_kills": 0,
                "drops_made": 0, "drops_value": 0,
                "drops_poor": 0,          # 雪中送炭 (drop while team eco/force)
                "drops_received": 0, "drops_value_received": 0,
                "drops_wasted": 0,        # received then died with 0 kills w/ it
                "drops_profitable": 0,    # received and got >=1 kill with it
                "free_pickups": 0,        # 白嫖枪 (picked primary, never bought it)
                "avg_dist_m": 0.0, "_dist_n": 0, "_dist_sum": 0.0, "max_dist_m": 0.0,
                "awp_kills": 0, "own_spend": 0,
                "rounds": len(reg),
            })
            if name:
                p["name"] = name
            return p

        # ---- round/team buy classes (economy heuristics, per side) ----
        purchase = build_purchase_log(demo)
        buys: dict[tuple[int, str], str] = {}
        for rnd_n, bucket in purchase.items():
            team_spend: dict[str, list[int]] = {"T": [], "CT": []}
            for sid, b in bucket.items():
                side = side_of.get(rnd_n, {}).get(sid, "")
                if side in team_spend:
                    team_spend[side].append(b["spend"])
            for side, spends in team_spend.items():
                if not spends:
                    continue
                avg = sum(spends) / len(spends)
                buys[(rnd_n, side)] = (
                    "eco" if avg < ECO_MAX else ("force" if avg < FORCE_MAX else "full"))
        res.buys = [{"round": k[0], "side": k[1], "buy": v} for k, v in buys.items()]

        # per-player ROUNDS PLAYED (present in side_of) — the METRIC_DEFS
        # denominators promise 出场回合数; using len(reg) (demo total)
        # diluted substitutes/late joiners
        rounds_played: dict[str, int] = defaultdict(int)
        for _rnd, per_sid in side_of.items():
            for sid in per_sid:
                rounds_played[sid] += 1

        def round_at(tick: int) -> int:
            for r in reg:
                if r.start_tick <= tick <= r.end_tick:
                    return r.number
            return 0

        def side_at(sid: str, tick: int) -> str:
            return side_of.get(round_at(tick), {}).get(sid, "")

        # ---- hurt pass: team dmg, per-victim damage history, attacker damage ----
        vic_hp_events: dict[str, list[tuple[int, str, float]]] = defaultdict(list)
        att_dmg_ticks: dict[str, list[tuple[int, float]]] = defaultdict(list)
        if hurt is not None and not hurt.empty:
            for _, row in hurt.iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start_tick:
                    continue
                att, vic = _s(row.get("attacker_steamid")), _s(row.get("user_steamid"))
                if not vic:
                    continue
                dh = _f(row.get("dmg_health"))
                if _s(row.get("user_name")):
                    P(vic, _s(row.get("user_name")))
                if att and att != vic and dh > 0:
                    a = P(att, _s(row.get("attacker_name")))
                    att_dmg_ticks[att].append((t, dh))
                    vic_hp_events[vic].append((t, att, dh))
                    if side_at(att, t) and side_at(att, t) == side_at(vic, t):
                        a["team_dmg"] += dh

        # ---- deaths rows (sorted) ----
        drows = []
        if deaths is not None and not deaths.empty:
            drows = [row for _, row in deaths.iterrows()
                     if int(row.get("tick", 0) or 0) >= start_tick and _s(row.get("user_steamid"))]
            drows.sort(key=lambda r: int(r.get("tick", 0) or 0))

        # per-victim life windows for whiff accounting; a life's end tick is
        # the death that closes it (被抢人头 finisher lookup is scoped to the
        # same life so softens can't be "stolen" across a death)
        life_windows: dict[str, list[tuple[int, int]]] = defaultdict(list)
        prev_end: dict[str, int] = {}
        for row in drows:
            vic = _s(row.get("user_steamid"))
            t = int(row.get("tick", 0) or 0)
            life_windows[vic].append((prev_end.get(vic, start_tick - 1) + 1, t))
            prev_end[vic] = t

        def life_span(vic: str, t: int) -> tuple[int, int]:
            """(start, end) of vic's life window containing tick t.

            end is the death tick that closes that life; a tick outside every
            window (still alive after their last death) gets an open-ended span.
            """
            for s0, e0 in life_windows.get(vic, ()):
                if s0 <= t <= e0:
                    return s0, e0
            return prev_end.get(vic, start_tick - 1) + 1, (1 << 62)

        # ---- whiff lives (<10 dmg dealt in a whole life) ----
        for att in set(att_dmg_ticks.keys()) | set(life_windows.keys()):
            p = P(att)
            p["lives"] += len(life_windows.get(att, []))
            tl = att_dmg_ticks.get(att, [])
            for s0, e0 in life_windows.get(att, []):
                dealt = sum(dh for t, dh in tl if s0 <= t <= e0)
                if dealt < WHIFF_DMG:
                    p["whiff_lives"] += 1

        # ---- per-death bookkeeping ----
        for row in drows:
            t = int(row.get("tick", 0) or 0)
            vic = _s(row.get("user_steamid"))
            att = _s(row.get("attacker_steamid"))
            P(vic, _s(row.get("user_name")))
            if att and att != vic:
                a = P(att, _s(row.get("attacker_name")))
                a["kills"] += 1
                pre_hp = _f(row.get("user_health", 100) or 100)
                # 抢人头: victim below the line AND another teammate had hit
                # them EARLIER IN THAT LIFE (life starts at the victim's
                # previous death; docstring promises "in that life")
                if pre_hp <= VULTURE_HP:
                    life_start, _life_end = life_span(vic, t)
                    others_hit = [a2 for t2, a2, dh in vic_hp_events.get(vic, [])
                                  if life_start <= t2 < t and a2 != att and a2 != vic and dh > 0
                                  and side_at(a2, t2) == side_at(att, t)]
                    if others_hit:
                        a["snipe_kills"] += 1
                # eco特 (enemy-eco round kills)
                rnd = round_at(t)
                att_side = side_at(att, t)
                vic_side = side_at(vic, t)
                if att_side and vic_side and att_side != vic_side:
                    if buys.get((rnd, vic_side)) == "eco":
                        a["eco_frag_opponent"] += 1
                    if buys.get((rnd, att_side)) == "eco":
                        a["eco_frag_self"] += 1
                # fun flags
                for flag, key in (("penetrated", "wallbang"), ("thrusmoke", "thrusmoke"),
                                  ("noscope", "noscope"), ("attackerblind", "blind"),
                                  ("attackerinair", "air")):
                    if _flag(row.get(flag)):
                        a[key] += 1
                wn = norm_weapon(row.get("weapon", ""))
                if "knife" in wn:
                    a["knife"] += 1
                elif wn in ("taser", "taser_projectile"):
                    a["taser"] += 1
                if wn == "awp":
                    a["awp_kills"] += 1
                # distance: demoparser2 emits METERS already (verified: max 49.3m
                # rifle kill, mean 15.6m — do NOT re-scale)
                dist = _f(row.get("distance"))
                if dist > 0:
                    a["_dist_n"] += 1
                    a["_dist_sum"] += dist
                    a["max_dist_m"] = max(a["max_dist_m"], round(dist, 1))
                # clutch: last alive on own side at this kill
                if att_side:
                    dead_before = sum(
                        1 for row2 in drows
                        if row2 is not row
                        and int(row2.get("tick", 0) or 0) < t
                        and round_at(int(row2.get("tick", 0) or 0)) == rnd
                        and side_at(_s(row2.get("user_steamid")), t) == att_side)
                    own_side_n = sum(1 for sid, s in side_of.get(rnd, {}).items() if s == att_side)
                    if own_side_n and own_side_n - dead_before <= 1:
                        a["clutch_kills"] += 1

        # ---- 被抢人头 + 死亡时刻索引（发枪/白嫖链共用）----
        death_tick_by_vic: dict[str, list[int]] = defaultdict(list)
        for row in drows:
            death_tick_by_vic[_s(row.get("user_steamid"))].append(int(row.get("tick", 0) or 0))
        # a "soften" = your hit took the victim's HP to <= line
        if hurt is not None and not hurt.empty and drows:
            # cumulative HP per victim walk (user_health gives pre-hit HP per row)
            hp_now: dict[str, float] = {}
            hurt_sorted = hurt.sort_values("tick")
            for _, row in hurt_sorted.iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start_tick:
                    continue
                vic = _s(row.get("user_steamid"))
                att = _s(row.get("attacker_steamid"))
                dh = _f(row.get("dmg_health"))
                hp_now[vic] = _f(row.get("user_health", 100) or 100)  # pre-hit HP
                if not att or att == vic or dh <= 0:
                    continue
                # did this hit take the victim to <= line for the first time?
                if hp_now[vic] - dh <= VULTURE_HP < hp_now[vic]:
                    # find the finish: vic's next death at/after the soften,
                    # still inside the SAME life window (a soften dies with
                    # the life it was dealt in)
                    _ls, life_end = life_span(vic, t)
                    finishes = [dt for dt in death_tick_by_vic.get(vic, [])
                                if t <= dt <= life_end]
                    if not finishes:
                        continue
                    dt = finishes[0]
                    # who finished? (death row attacker at dt)
                    finisher = next((_s(r2.get("attacker_steamid")) for r2 in drows
                                     if _s(r2.get("user_steamid")) == vic
                                     and int(r2.get("tick", 0) or 0) == dt), "")
                    if finisher and finisher != att:
                        a = P(att, _s(row.get("attacker_name")))
                        if side_at(finisher, dt) == side_at(att, t):
                            a["stolen_from"] += 1

        # ---- trade ledger + teammate-death opportunities ----
        for i, row in enumerate(drows):
            t = int(row.get("tick", 0) or 0)
            vic = _s(row.get("user_steamid"))
            killer = _s(row.get("attacker_steamid"))
            vic_side = side_at(vic, t)
            # every death of a player is a "revenge opportunity" for their
            # living teammates (denominator of 复仇率)
            if vic_side:
                for sid, s in side_of.get(round_at(t), {}).items():
                    if s == vic_side and sid != vic:
                        P(sid)["teammate_deaths"] += 1
            for row2 in drows[i + 1:]:
                t2 = int(row2.get("tick", 0) or 0)
                if t2 - t > TRADE_WINDOW_TICKS:
                    break
                av = _s(row2.get("attacker_steamid"))
                cv = _s(row2.get("user_steamid"))
                if not av or not killer or av == killer:
                    continue
                if cv == killer:  # avenger killed the original killer
                    if vic_side and side_at(av, t2) == vic_side:
                        P(vic, _s(row.get("user_name")))["traded_deaths"] += 1
                        P(av, _s(row2.get("attacker_name")))["avenges"] += 1
                    break

        # ---- weapon-drop chain (发枪) ----
        pu_rows = []
        for rnd_n, bucket in purchase.items():
            for sid, b in bucket.items():
                for w in b["weapons"]:
                    wn = norm_weapon(w)
                    if wn in PRIMARY_WEAPONS:
                        pu_rows.append((rnd_n, sid, wn, b.get("spend", 0)))
        # cost per weapon: purchase log aggregates spend per player per round;
        # re-read exact rows for per-weapon cost
        if demo.events.get("item_purchase") is not None and not demo.events["item_purchase"].empty:
            ip = demo.events["item_purchase"]
            exact = defaultdict(int)  # (round, sid, weapon) -> cost
            for _, row in ip.iterrows():
                rn = round_at(int(row.get("tick", 0) or 0))
                if not rn:
                    continue
                wn = norm_weapon(row.get("item_name", row.get("weapon", "")))
                if wn in PRIMARY_WEAPONS:
                    exact[(rn, _s(row.get("steamid") or row.get("user_steamid")), wn)] += int(_f(row.get("cost")))
            self_buy_ticks: dict[tuple[str, str, int], list[int]] = defaultdict(list)
            for _, row in ip.iterrows():
                t = int(row.get("tick", 0) or 0)
                rn = round_at(t)
                if not rn:
                    continue
                wn = norm_weapon(row.get("item_name", row.get("weapon", "")))
                sid = _s(row.get("steamid") or row.get("user_steamid"))
                if wn in PRIMARY_WEAPONS:
                    self_buy_ticks[(sid, wn, rn)].append(t)

            pickups = demo.events.get("item_pickup")
            if pickups is not None and not pickups.empty:
                for _, prow in pickups.iterrows():
                    t2 = int(prow.get("tick", 0) or 0)
                    if t2 < start_tick:
                        continue
                    wn = norm_weapon(prow.get("item", ""))
                    if wn not in PRIMARY_WEAPONS:
                        continue
                    B = _s(prow.get("user_steamid"))
                    rn = round_at(t2)
                    if not rn or not B:
                        continue
                    # skip own purchases (buy emits pickup) — own buy same round
                    if t2 in self_buy_ticks.get((B, wn, rn), []):
                        continue
                    # find donor candidates this round
                    cands = []
                    for (r2, sid2, w2), cost in exact.items():
                        if r2 != rn or w2 != wn or sid2 == B:
                            continue
                        for t1 in self_buy_ticks.get((sid2, wn, rn), []):
                            if t1 < t2 and t2 - t1 <= DROP_WINDOW_TICKS:
                                # donor alive at pickup?
                                alive = not any(
                                    _s(r3.get("user_steamid")) == sid2
                                    and t1 <= int(r3.get("tick", 0) or 0) <= t2
                                    for r3 in drows)
                                if alive:
                                    cands.append((t1, sid2, cost))
                    if not cands:
                        continue
                    t1, A, cost = min(cands)
                    a = P(A, _s(next((r2.get("attacker_name") for r2 in drows
                                      if _s(r2.get("attacker_steamid")) == A), A)))
                    b = P(B, _s(prow.get("user_name") or B))
                    a["drops_made"] += 1
                    a["drops_value"] += cost
                    b["drops_received"] += 1
                    b["drops_value_received"] += cost
                    # 雪中送炭: donor's side was on eco/force this round
                    if buys.get((rn, side_at(A, t1))) in ("eco", "force"):
                        a["drops_poor"] += 1
                    # outcome for the receiver: kills with this weapon before
                    # their death or the ROUND END (docstring/口径 says 当回合 —
                    # kills in later rounds with the same gun don't credit
                    # this drop); 0 kills + died = wasted
                    kills_w = 0
                    died_after = False
                    for r2 in drows:
                        vt = int(r2.get("tick", 0) or 0)
                        if _s(r2.get("user_steamid")) == B and vt >= t2:
                            died_after = True
                            break
                    rnd_bounds = next((r for r in reg if r.number == rn), None)
                    round_end = rnd_bounds.end_tick if rnd_bounds else (1 << 62)
                    vt_cap = vt_limit(drows, B, t2) if died_after else round_end
                    cap = min(vt_cap, round_end)
                    # count B's kills with wn between pickup and cap
                    if demo.events.get("player_death") is not None:
                        for _, krow in demo.events["player_death"].iterrows():
                            kt = int(krow.get("tick", 0) or 0)
                            if kt < t2 or kt > cap:
                                continue
                            if _s(krow.get("attacker_steamid")) != B:
                                continue
                            if norm_weapon(krow.get("weapon", "")) != wn:
                                continue
                            kills_w += 1
                    if died_after and kills_w == 0:
                        b["drops_wasted"] += 1
                    elif kills_w >= 1:
                        a["drops_profitable"] += 1
                    res.drops.append({"round": rn, "donor": A, "receiver": B,
                                      "weapon": wn, "cost": cost})

        # ---- own spend (for generosity denominators) + eco opportunities ----
        if demo.events.get("item_purchase") is not None and not demo.events["item_purchase"].empty:
            for _, row in demo.events["item_purchase"].iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start_tick:
                    continue
                sid = _s(row.get("steamid") or row.get("user_steamid"))
                if sid:
                    P(sid)["own_spend"] += int(_f(row.get("cost")))
        # kills per (player, round) — shared by 叛逆者 and 多杀率
        kills_per_round: dict[tuple[str, int], int] = defaultdict(int)
        if demo.events.get("player_death") is not None and not demo.events["player_death"].empty:
            for _, row in demo.events["player_death"].iterrows():
                t = int(row.get("tick", 0) or 0)
                if t < start_tick:
                    continue
                att = _s(row.get("attacker_steamid"))
                rn = round_at(t)
                if att and rn:
                    kills_per_round[(att, rn)] += 1
        for (rnd, side), cls in buys.items():
            if cls != "eco":
                continue
            for sid, s in side_of.get(rnd, {}).items():
                if s == side:
                    P(sid)["eco_rounds_played"] += 1
        # eco 局个性打法三分（用户命名，v5 口径审计裁决 2026-09-05）:
        #   叛逆者 = 全队唯一买长枪（RIFLE_WEAPONS——沙鹰鸟狙不算，
        #            鸟狙=装逼枪是用户裁决，v4 文档"狙类含SSG"作废）
        #   装逼   = 买沙鹰或鸟狙、且未买长枪（"我就想玩个心跳"）
        #   纯eco  = 整回合消费 <500$（几乎裸吊）
        rifle_buyers: dict[tuple[int, str], list[str]] = defaultdict(list)  # (round, side) -> sids
        per_player_eco = defaultdict(lambda: {"rifles": set(), "showoff": set(), "spend": 0})
        if demo.events.get("item_purchase") is not None and not demo.events["item_purchase"].empty:
            for _, row in demo.events["item_purchase"].iterrows():
                t = int(row.get("tick", 0) or 0)
                rn2 = round_at(t)
                if not rn2:
                    continue
                sid2 = _s(row.get("steamid") or row.get("user_steamid"))
                s2 = side_of.get(rn2, {}).get(sid2, "")
                if buys.get((rn2, s2)) != "eco":
                    continue
                wn2 = norm_weapon(row.get("item_name", row.get("weapon", "")))
                rec = per_player_eco[(sid2, rn2)]
                rec["spend"] += int(_f(row.get("cost")))
                if wn2 in RIFLE_WEAPONS:
                    rec["rifles"].add(wn2)
                    rifle_buyers[(rn2, s2)].append(sid2)
                if wn2 in SHOWOFF_WEAPONS:
                    rec["showoff"].add(wn2)
        for (rnd, side), buyers in rifle_buyers.items():
            if len(set(buyers)) != 1:
                continue  # 多人齐起 = 团队决定，非叛逆
            sid = buyers[0]
            p = P(sid)
            p["rebel_rounds"] += 1
            r = reg[rnd - 1]
            if r.winner_side == side:
                p["rebel_wins"] += 1
            p["rebel_kills"] += kills_per_round.get((sid, rnd), 0)
        # 装逼 / 纯eco (per eco-round classification)
        for (sid, rnd), rec in per_player_eco.items():
            p = P(sid)
            if rec["rifles"]:
                continue  # 起了长枪 -> 叛逆者口径已计
            if rec["showoff"]:
                p["showoff_rounds"] += 1
            elif rec["spend"] < 500:
                p["pure_eco_rounds"] += 1
        # Jame index inputs: team-lost rounds + survived losses per player
        for r in reg:
            if not r.winner_side:
                continue
            for sid, s in side_of.get(r.number, {}).items():
                if s == r.winner_side:
                    continue
                p = P(sid)
                p["team_lost_rounds"] += 1
                died = any(_s(row2.get("user_steamid")) == sid
                           and int(row2.get("tick", 0) or 0) >= r.start_tick
                           and int(row2.get("tick", 0) or 0) <= r.end_tick
                           for row2 in drows)
                if not died:
                    p["survived_losses"] += 1
        for (att, _rn), n in kills_per_round.items():
            if n >= 2:
                P(att)["multi_rounds"] += 1
        # 白嫖枪: primary pickups that were neither own-buys nor detected drops
        received_keys = {(d["round"], d["receiver"], d["weapon"]) for d in res.drops}
        pickups = demo.events.get("item_pickup")
        if pickups is not None and not pickups.empty:
            for _, prow in pickups.iterrows():
                wn = norm_weapon(prow.get("item", ""))
                if wn not in PRIMARY_WEAPONS:
                    continue
                t2 = int(prow.get("tick", 0) or 0)
                B = _s(prow.get("user_steamid"))
                rn = round_at(t2)
                if not rn or not B or t2 < start_tick:
                    continue
                if t2 in self_buy_ticks.get((B, wn, rn), []):
                    continue
                if (rn, B, wn) in received_keys:
                    continue
                # 白嫖 = 捡到已阵亡队友购买的同款武器（吸血语义）。
                # 地上敌人的枪是正常战利品，不计。
                # 死亡窗口判定：队友 C 本回合买过 w 且 C 的死亡时刻落在
                # [C购买时刻, B拾取时刻] 内（C 死了枪才掉，B 才捡得到）。
                mate_died = False
                b_side = side_at(B, t2)
                # keys are (sid, wn, rn) — unpack in that order (a (r2, sid2, w2)
                # unpack here silently compared round vs steamid: always True skip)
                for (sid2, w2, r2), ts in self_buy_ticks.items():
                    if r2 != rn or w2 != wn or sid2 == B:
                        continue
                    cand_side = side_at(sid2, ts[0])
                    death_ticks = [dt for dt in death_tick_by_vic.get(sid2, []) if dt < t2]
                    if cand_side != b_side:
                        continue
                    if any(bt <= dt for bt in ts for dt in death_ticks):
                        mate_died = True
                        break
                if mate_died:
                    P(B, _s(prow.get("user_name") or B))["free_pickups"] += 1

        # ---- derive per-player rates/means ----
        for p in players.values():
            k = max(p["kills"], 1)
            # keep sums so the web memo can average across demos correctly;
            # per-demo "rounds played" replaces the demo-total len(reg) so
            # substitutes aren't diluted (METRIC_DEFS: 出场回合数)
            p["rounds"] = rounds_played.get(p["steamid"], p["rounds"])
            p["dist_sum"] = round(p["_dist_sum"], 1)
            p["dist_n"] = p["_dist_n"]
            del p["_dist_n"], p["_dist_sum"]
            p["snipe_rate"] = round(p["snipe_kills"] / k, 3)
            p["awp_rate"] = round(p["awp_kills"] / k, 3)
            p["whiff_rate"] = round(p["whiff_lives"] / max(p["lives"], 1), 3)
            p["team_dmg_rpr"] = round(p["team_dmg"] / max(p["rounds"], 1), 2)
            p["drop_generosity"] = round(p["drops_value"] / max(p["own_spend"], 1), 3)
            p["drop_poor_share"] = round(p["drops_poor"] / max(p["drops_made"], 1), 3)
            p["drop_waste_rate"] = round(p["drops_wasted"] / max(p["drops_received"], 1), 3)
            p["eco_hard_rate"] = round(p["eco_frag_self"] / max(p["eco_rounds_played"], 1), 3)
            p["jame_index"] = round(p["survived_losses"] / max(p["team_lost_rounds"], 1), 3)
            p["revenge_rate"] = round(p["avenges"] / max(p["teammate_deaths"], 1), 3)
            p["avenged_rate"] = round(p["traded_deaths"] / max(p["lives"], 1), 3)
            p["rebel_rate"] = round(p["rebel_rounds"] / max(p["eco_rounds_played"], 1), 3)
            p["rebel_win_rate"] = round(p["rebel_wins"] / max(p["rebel_rounds"], 1), 3)
            p["showoff_rate"] = round(p["showoff_rounds"] / max(p["eco_rounds_played"], 1), 3)
            p["pure_eco_rate"] = round(p["pure_eco_rounds"] / max(p["eco_rounds_played"], 1), 3)
            p["team_dmg"] = round(p["team_dmg"], 1)
        res.players = list(players.values())
        return res


def vt_limit(drows, sid: str, since: int) -> int:
    """The tick of sid's next death at/after `since` (or +inf if none)."""
    for r2 in drows:
        if _s(r2.get("user_steamid")) == sid:
            t = int(r2.get("tick", 0) or 0)
            if t >= since:
                return t
    return 1 << 62
