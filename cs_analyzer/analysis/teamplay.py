"""K5: five-stack teamplay analytics over the local 5E demo library.

All signals derive from cached ParsedDemos (no re-parse):

- Link network (K5a): per steamid pair, directed
    * assists       - A assisted B's kill (player_death.assister)
    * flash assists - subset where assistedflash is True
    * trades        - B avenged A: A died by X, B killed X within
                      TRADE_WINDOW_TICKS (same semantics as ratings.py)
- Regulars (K5b): players appearing in >= min_regular_demos of the 5E set.
  A 5E demo where >= stack_threshold regulars played together is a
  "five-stack match"; the rest of the 5E set is "mixed".
  Compared per group: round win rate of the stack side, avg Rating,
  first-kill success rate.
- Portraits (K5c): one label each for best partner / flasher / entry /
  clutch among the regulars.

NOTE on provider: 5E demos report provider='valve' (their servers emit
plain SourceTV headers), so the 5E library is identified by the
'g161-' filename prefix (the same prefix K3 extracts match ids from),
not by ProviderKind.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from cs_analyzer.analysis.highlights import HighlightsModule
from cs_analyzer.analysis.ratings import TRADE_WINDOW_TICKS
from cs_analyzer.analysis.util import round_player_sides
from cs_analyzer.model.parsed_demo import ParsedDemo

FIVE_E_PREFIX = "g161-"
# K5c: minimum opening duels before a first-kill rate is trusted
MIN_FK_DUELS = 10


def is_five_e(demo: ParsedDemo) -> bool:
    return Path(demo.metadata.demo_path).name.startswith(FIVE_E_PREFIX)


def _first_kills(demo: ParsedDemo) -> tuple[Counter, Counter]:
    """Per player: opening-duel wins (their kill was the round's first) and
    losses (they were the first kill's victim)."""
    wins: Counter = Counter()
    losses: Counter = Counter()
    deaths = demo.events.get("player_death")
    if deaths is None or deaths.empty or "tick" not in deaths.columns:
        return wins, losses
    deaths = deaths.copy()
    for col in ("user_steamid", "attacker_steamid"):
        if col in deaths.columns:
            deaths[col] = deaths[col].fillna("")
    for rnd in demo.regular_rounds:
        window = deaths[
            (deaths["tick"] >= rnd.start_tick) & (deaths["tick"] < rnd.end_tick)
        ].sort_values("tick")
        if window.empty:
            continue
        row = window.iloc[0]
        att = str(row.get("attacker_steamid", "") or "")
        vic = str(row.get("user_steamid", "") or "")
        if att and att != vic:
            wins[att] += 1
        if vic:
            losses[vic] += 1
    return wins, losses


def _pair_links(demo: ParsedDemo, sides: dict[int, dict[str, str]]) -> dict:
    """Directed pair connections from one demo's kill feed."""
    links: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"assists": 0, "trades": 0, "flash_assists": 0}
    )
    deaths = demo.events.get("player_death")
    if deaths is None or deaths.empty:
        return links
    rows = deaths.sort_values("tick").reset_index(drop=True)
    # steamid columns are float-NaN when a broadcast omits the attacker or
    # assister — NaN.astype(str) would invent a fake "nan" player
    for col in ("user_steamid", "attacker_steamid", "assister_steamid"):
        if col in rows.columns:
            rows[col] = rows[col].fillna("")
    ticks = rows["tick"].astype(int).tolist()
    victims = rows["user_steamid"].astype(str).tolist()
    killers = rows["attacker_steamid"].astype(str).tolist()
    has_assist = "assister_steamid" in rows.columns
    assisters = rows["assister_steamid"].astype(str).tolist() if has_assist else [""] * len(rows)
    has_aflash = "assistedflash" in rows.columns

    for i in range(len(rows)):
        k, v = killers[i], victims[i]
        # ---- assists (assister helped the killer; flash subset flagged) ----
        a = assisters[i]
        if a and a != k and a != v:
            links[(a, k)]["assists"] += 1
            if has_aflash and bool(rows.iloc[i].get("assistedflash", False)):
                links[(a, k)]["flash_assists"] += 1
        # ---- trades: v's teammate avenges v by killing k within the window
        if not k or k == v:
            continue
        rnd = demo.data.round_at_tick(ticks[i])
        if rnd is None:
            continue
        side_map = sides.get(rnd.number, {})
        v_side = side_map.get(v, "")
        if not v_side:
            continue
        limit = ticks[i] + TRADE_WINDOW_TICKS
        for j in range(i + 1, len(rows)):
            if ticks[j] > limit:
                break
            if victims[j] == k and killers[j] and killers[j] != k:
                # the avenger must be on the avenged player's side
                if side_map.get(killers[j], "") == v_side:
                    links[(killers[j], v)]["trades"] += 1
                break  # k died once; its revenge is the first death of k
    return links


def build_teamplay_report(
    cache_dir: Path,
    *,
    min_regular_demos: int = 3,
    stack_threshold: int = 3,
    demo_ratings: dict[str, dict[str, float]] | None = None,
) -> dict:
    """Cross-demo five-stack report (see module docstring).

    Thresholds: the local 5E library's stable core is CCTV909 (9/9) plus
    FywOo6666/杏愛 (5x each) and FENNEL的YamZzi本人 (3x) — a >=4-regulars
    rule (the original K5 plan) yields ZERO stack matches, so the defaults
    are >=3 appearances = regular, >=3 regulars in one match = stack.

    demo_ratings: optional {demo_hash: {steamid: Rating}} — pass the web
    aggregate's per-demo ratings to avoid recomputing; when omitted the
    ratings module runs over the 5E demos (CLI path).
    """
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.config import AnalysisConfig
    from cs_analyzer.analysis.library import demo_filenames, scan_demos

    cache = DemoCache(Path(cache_dir))
    # metadata-only pre-read: only the 5E subset (g161- filename prefix)
    # needs full loads — the WMPVP half of the library is counted, not read.
    names = demo_filenames(Path(cache_dir))
    five_e_hashes = [h for h, fn in names.items() if fn.startswith(FIVE_E_PREFIX)]
    five_e = [dm for h in five_e_hashes if (dm := cache.load(h)) is not None]
    demos_total = len(names)

    # ---- regulars: appearance count across the 5E set ----
    appear: Counter = Counter()
    names: dict[str, str] = {}
    for dm in five_e:
        for p in dm.players:
            appear[p.steamid] += 1
            names[p.steamid] = p.name
    regulars = {sid for sid, n in appear.items() if n >= min_regular_demos}

    # ---- K5a: link network across all 5E demos ----
    agg_links: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"assists": 0, "trades": 0, "flash_assists": 0, "demos": set()}
    )
    per_demo_links: dict[str, dict] = {}
    for dm in five_e:
        sides = round_player_sides(dm)
        demo_links = _pair_links(dm, sides)
        per_demo_links[dm.metadata.demo_hash] = demo_links
        for (a, b), counts in demo_links.items():
            tgt = agg_links[(a, b)]
            for key in ("assists", "trades", "flash_assists"):
                tgt[key] += counts[key]
            tgt["demos"].add(dm.metadata.demo_hash)

    links_out = []
    for (a, b), c in agg_links.items():
        weight = c["assists"] + c["trades"] + c["flash_assists"]
        if weight <= 0:
            continue
        links_out.append({
            "a_sid": a, "a_name": names.get(a, a),
            "b_sid": b, "b_name": names.get(b, b),
            "assists": c["assists"], "trades": c["trades"],
            "flash_assists": c["flash_assists"],
            "weight": weight, "demos": len(c["demos"]),
        })
    links_out.sort(key=lambda x: x["weight"], reverse=True)

    # ---- K5b: stack classification + group comparison ----
    runner = None
    if demo_ratings is None:
        from cs_analyzer.analysis.runner import AnalysisRunner

        runner = AnalysisRunner(
            AnalysisConfig(enabled_modules=["basic_stats", "ratings"]))

    matches = []
    group = {
        "stack": {"rounds_won": 0, "rounds_total": 0, "ratings": [], "fk_wins": 0, "fk_duels": 0},
        "mixed": {"rounds_won": 0, "rounds_total": 0, "ratings": [], "fk_wins": 0, "fk_duels": 0},
    }
    fk_wins_total: Counter = Counter()
    fk_losses_total: Counter = Counter()
    clutch_wins: Counter = Counter()
    flash_given: Counter = Counter()
    for (a, _b), c in agg_links.items():
        flash_given[a] += c["flash_assists"]

    for dm in five_e:
        in_match = [p.steamid for p in dm.players if p.steamid in regulars]
        is_stack = len(in_match) >= stack_threshold
        key = "stack" if is_stack else "mixed"
        sides = round_player_sides(dm)
        rounds = dm.regular_rounds
        # stack side per round: majority side of the regulars present; only
        # rounds where every present regular is on ONE side count (true stack)
        swon = stot = 0
        for rnd in rounds:
            smap = sides.get(rnd.number, {})
            present = [smap.get(sid, "") for sid in in_match if smap.get(sid)]
            if not present:
                continue
            t_n, ct_n = present.count("T"), present.count("CT")
            if (t_n > 0) != (ct_n > 0):
                stot += 1
                if rnd.winner_side == ("T" if t_n > 0 else "CT"):
                    swon += 1
        group[key]["rounds_won"] += swon
        group[key]["rounds_total"] += stot

        demo_r: dict[str, float] = {}
        if demo_ratings is not None:
            demo_r = demo_ratings.get(dm.metadata.demo_hash, {})
        else:
            assert runner is not None
            results = runner.run(dm)
            rt = results.get("ratings")
            if rt is not None:
                demo_r = {p.steamid: p.Rating for p in rt.players}

        w, l = _first_kills(dm)
        fk_wins_total.update(w)
        fk_losses_total.update(l)
        hl = HighlightsModule().run(dm, _ctx()).highlights
        for h in hl:
            if h.kind == "clutch":
                clutch_wins[h.steamid] += 1

        for sid in in_match:
            if sid in demo_r:
                group[key]["ratings"].append(demo_r[sid])
            group[key]["fk_duels"] += w[sid] + l[sid]
            group[key]["fk_wins"] += w[sid]

        matches.append({
            "demo_hash": dm.metadata.demo_hash,
            "filename": Path(dm.metadata.demo_path).name,
            "map": dm.metadata.map_name,
            "match_id": getattr(dm.metadata, "match_id", None),
            "rounds": len(rounds),
            "stack_size": len(in_match),
            "is_stack": is_stack,
            "stack_round_win_rate": round(swon / stot, 3) if stot else None,
            "stack_rounds": stot,
            "regulars": [names.get(s, s) for s in in_match],
        })

    def _grp(key: str) -> dict:
        g = group[key]
        return {
            "round_win_rate": round(g["rounds_won"] / g["rounds_total"], 3) if g["rounds_total"] else None,
            "rounds": g["rounds_total"],
            "avg_rating": round(sum(g["ratings"]) / len(g["ratings"]), 3) if g["ratings"] else None,
            "fk_success": round(g["fk_wins"] / g["fk_duels"], 3) if g["fk_duels"] else None,
            "fk_duels": g["fk_duels"],
            "player_samples": len(g["ratings"]),
        }

    stack_vs_mixed = {
        "stack_matches": sum(1 for m in matches if m["is_stack"]),
        "mixed_matches": sum(1 for m in matches if not m["is_stack"]),
        "stack": _grp("stack"),
        "mixed": _grp("mixed"),
    }

    # ---- K5c: portraits for the regulars ----
    reg_top_flash = max(regulars, key=lambda s: flash_given[s], default=None)
    duels_of = lambda s: fk_wins_total[s] + fk_losses_total[s]  # noqa: E731
    fk_eligible = [s for s in regulars if duels_of(s) >= MIN_FK_DUELS]
    reg_top_fk = max(fk_eligible, key=lambda s: fk_wins_total[s] / duels_of(s), default=None) \
        if fk_eligible else None
    reg_top_clutch = max(regulars, key=lambda s: clutch_wins[s], default=None)

    link_weight: dict[str, dict[str, int]] = defaultdict(dict)
    for (a, b), c in agg_links.items():
        wgt = c["assists"] + c["trades"] + c["flash_assists"]
        link_weight[a][b] = max(link_weight[a].get(b, 0), wgt)

    portraits = []
    for sid in sorted(regulars, key=lambda s: -appear[s]):
        labels = []
        if reg_top_flash and sid == reg_top_flash and flash_given[sid] > 0:
            labels.append({"label": "闪光发动机", "detail": f"{flash_given[sid]} 次闪光助攻"})
        if reg_top_fk and sid == reg_top_fk:
            labels.append({
                "label": "首杀先锋",
                "detail": f"首杀成功率 {fk_wins_total[sid] / duels_of(sid):.0%}"
                          f" ({fk_wins_total[sid]}/{duels_of(sid)})",
            })
        if reg_top_clutch and sid == reg_top_clutch and clutch_wins[sid] > 0:
            labels.append({"label": "残局大师", "detail": f"{clutch_wins[sid]} 次残局获胜"})
        best = None
        partners = sorted(link_weight.get(sid, {}).items(), key=lambda kv: -kv[1])
        if partners:
            pid, wgt = partners[0]
            best = {"steamid": pid, "name": names.get(pid, pid), "weight": wgt}
        portraits.append({
            "steamid": sid, "name": names.get(sid, sid),
            "appearances": appear[sid],
            "best_partner": best,
            "labels": labels,
            "fk_success": round(fk_wins_total[sid] / duels_of(sid), 3) if duels_of(sid) else None,
            "clutch_wins": clutch_wins[sid],
            "flash_assists": flash_given[sid],
        })

    # ---- heatmap matrix (symmetric weight between regulars, capped 12) ----
    reg_sorted = sorted(regulars, key=lambda s: -appear[s])[:12]
    idx = {sid: i for i, sid in enumerate(reg_sorted)}
    matrix = [[0] * len(reg_sorted) for _ in reg_sorted]
    for (a, b), c in agg_links.items():
        if a in idx and b in idx and a != b:
            wgt = c["assists"] + c["trades"] + c["flash_assists"]
            matrix[idx[a]][idx[b]] += wgt
            matrix[idx[b]][idx[a]] += wgt

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "library": {"five_e_demos": len(five_e), "total_demos": demos_total,
                    "min_regular_demos": min_regular_demos,
                    "stack_threshold": stack_threshold},
        "regulars": [{"steamid": s, "name": names.get(s, s), "appearances": appear[s]}
                     for s in reg_sorted],
        "links": links_out,
        "matrix": {"players": [names.get(s, s) for s in reg_sorted], "values": matrix},
        "matches": matches,
        "stack_vs_mixed": stack_vs_mixed,
        "portraits": portraits,
    }


def _ctx():
    from cs_analyzer.analysis.base import AnalysisContext
    from cs_analyzer.config import AnalysisConfig

    return AnalysisContext(AnalysisConfig())
