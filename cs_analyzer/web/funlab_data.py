"""Memoized cross-demo fun-metrics report (Phase M 趣味数据实验室).

Merges FunLabModule per-demo results across the library into per-player
vectors, enforces the appearance gate (>= MIN_DEMOS demos — user-set at 3),
and derives the USER-APPROVED metric pool (docs/funlab-metrics.md v2).

Axes are ratios/means only (never "played more -> bigger number");
absolute values live in tooltips and the money boards only.

Filters (user request): lineup size (单排/双排/3排/4排/5排 — count of library
regulars in the match) and match date (from the 5E filename's embedded date).
The expensive whole-library scan is cached separately; filters re-merge
cheaply per request.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict

_lock = threading.Lock()
_scan: dict | None = None      # expensive whole-library per-demo vectors
_report: dict | None = None    # last merged report (any filter combo)
_report_key: tuple | None = None

#: chart gate — players with fewer appearances never enter /fun-lab
MIN_DEMOS = 3

_DATE_RE = re.compile(r"(\d{8})")

# ---- 指标口径字典（v5 口径审计：网页"点开看口径"的唯一数据源）----
# formula = 计算公式（分子/分母），note = 口径边界与已知偏差。
# 与 docs/funlab-metrics.md 保持同义；页面按此渲染，勿在前端重复硬编码。
METRIC_DEFS: dict[str, dict[str, str]] = {
    # ---- 经济系 ----
    "drop_generosity": {"label": "发枪慷慨率", "pct": True,
        "formula": "发给队友的枪价值 ÷ 自己总购买花费",
        "note": "分母=该选手全部 item_purchase 金额。发枪由购买→拾取链反推：同回合、同款主武器、拾取者未自购、购买者存活、30s 窗口。"},
    "vulture_rate": {"label": "吸血率（被供枪）", "pct": True,
        "formula": "被发枪价值 ÷ (自己购买花费 + 被发枪价值)",
        "note": "装备来源里队友供枪占比，0.4 = 四成装备是队友喂的。"},
    "drop_poor_share": {"label": "雪中送炭占比", "pct": True,
        "formula": "己方处于 eco/force 局时的发枪次数 ÷ 总发枪次数",
        "note": "自己没钱还发枪的意愿。回合分类按队伍平均消费：<2000$ eco、<3700$ force。"},
    "drop_profit_rate": {"label": "发枪成材率", "pct": True,
        "formula": "被发枪者当回合用该枪拿到 ≥1 杀的发枪数 ÷ 总发枪次数",
        "note": "武器级归属，测这把枪有没有打水漂。收枪者存活到底但 0 杀不计入分子。"},
    "drop_waste_rate": {"label": "浪费发枪率", "pct": True,
        "formula": "被发枪后同回合死亡且 0 杀的次数 ÷ 被发枪次数",
        "note": "分母=收到发枪的次数（白嫖枪不算）。"},
    "showoff_rate": {"label": "装逼率（eco局沙鹰/鸟狙）", "pct": True,
        "formula": "eco 局买沙鹰或鸟狙且未买长枪的回合数 ÷ 己方 eco 回合数",
        "note": "用户裁决：起沙鹰、起鸟狙=想装逼（一枪秒人/赌一枪命中）。若同时买了长枪→按叛逆者计，不算装逼。"},
    "pure_eco_rate": {"label": "纯eco率（eco局裸吊）", "pct": True,
        "formula": "eco 局整回合消费 <500$ 的回合数 ÷ 己方 eco 回合数",
        "note": "装逼与纯eco互斥：先判长枪（叛逆）→再判装逼枪→最后判纯eco。"},
    "rebel_rate": {"label": "叛逆起枪率（eco局长枪）", "pct": True,
        "formula": "eco 局全队唯一买长枪的回合数 ÷ 己方 eco 回合数",
        "note": "长枪=AK/M4/Galil/FAMAS/AUG/SG/AWP（鸟狙不算，用户裁决）。多人齐起=团队决定，不算叛逆。"},
    "rebel_win_rate": {"label": "赌狗胜率（叛逆局）", "pct": True,
        "formula": "叛逆局获胜数 ÷ 叛逆局数",
        "note": "小样本陷阱：必须连同局数一起看（页面显示 N局M胜），1局1胜=100% 无意义。"},
    "free_pickup_rate": {"label": "白嫖占比（收枪中白嫖）", "pct": True,
        "formula": "白嫖枪次数 ÷ (被发枪次数 + 白嫖枪次数)",
        "note": "白嫖=捡到阵亡队友购买的同款主武器（死亡窗口判定）；地上敌人的枪是正常战利品，不计。"},
    "free_pickup_pr": {"label": "白嫖频率（每回合）", "pct": False,
        "formula": "白嫖枪总次数 ÷ 总回合数",
        "note": "舔包王榜排序口径（用户裁决：除总回合数，场次多不占便宜）。"},
    # ---- 击杀系 ----
    "eco_frag_rate": {"label": "eco特率", "pct": True,
        "formula": "对手处于 eco 局时的击杀数 ÷ 总击杀数",
        "note": "只对对手 eco 算（force 杀不算）——低含金量击杀占比。"},
    "eco_hard_rate": {"label": "神仙率（每eco局）", "pct": True,
        "formula": "己方 eco 局击杀数 ÷ 己方 eco 回合数",
        "note": "机会口径：每局 eco 平均产出，避免 eco 局多的选手天然数值大。"},
    "whiff_rate": {"label": "白给率", "pct": True,
        "formula": "伤害 <10 的命 ÷ 总死亡数",
        "note": "按生命（两次死亡之间）累计 dmg_health，血包/护甲不算。分母是死亡数——全程存活不产生白给机会。"},
    "snipe_rate": {"label": "抢人头率", "pct": True,
        "formula": "终击时受害者 HP≤30 且其他队友曾对其造成伤害的击杀数 ÷ 总击杀数",
        "note": "自己打残自己收不算（归因要求队友≠终结者）。HP 线=30。"},
    "stolen_rate": {"label": "被抢人头率", "pct": True,
        "formula": "被打到 HP≤30 后由队友终结的次数 ÷ (击杀数 + 被抢次数)",
        "note": "你参与终结的敌人里，人头被队友拿走的比例。按 HP 首次跌破 30 归因。"},
    "clutch_freq": {"label": "残局频率", "pct": True,
        "formula": "last-alive 状态下的击杀数 ÷ 出场回合数",
        "note": "击杀瞬间己方仅剩你存活。1v1 收头也算，宽松口径。"},
    "multi_rate": {"label": "多杀率", "pct": True,
        "formula": "击杀 ≥2 的回合数 ÷ 出场回合数", "note": ""},
    "avg_dist_m": {"label": "平均交战距离(m)", "pct": False,
        "formula": "全部击杀距离（米）的加权平均",
        "note": "demoparser2 的 distance 本身就是米，不再换算。最远击杀记录在 tooltip。"},
    "awp_rate": {"label": "狙击依赖", "pct": True,
        "formula": "AWP 击杀数 ÷ 总击杀数",
        "note": "5E 皮肤名（5e_xxx_awp）已归一为 base name。"},
    # ---- 花活系（全部 ÷ 总击杀）----
    "wallbang_rate": {"label": "穿墙杀率", "pct": True, "formula": "penetrated=True 的击杀 ÷ 总击杀数", "note": ""},
    "thrusmoke_rate": {"label": "烟中杀率", "pct": True, "formula": "thrusmoke=True 的击杀 ÷ 总击杀数", "note": ""},
    "noscope_rate": {"label": "盲狙率", "pct": True, "formula": "noscope=True 的击杀 ÷ 总击杀数", "note": ""},
    "blind_rate": {"label": "致盲杀率", "pct": True, "formula": "attackerblind=True（击杀瞬间攻击者被闪）÷ 总击杀数", "note": ""},
    "air_rate": {"label": "空中杀率", "pct": True, "formula": "attackerinair=True 的击杀 ÷ 总击杀数", "note": ""},
    "knife_rate": {"label": "刀杀率", "pct": True, "formula": "武器名含 knife 的击杀 ÷ 总击杀数", "note": ""},
    "flags_rate": {"label": "花活合计率", "pct": True,
        "formula": "(穿墙+烟中+盲狙+致盲+空中+刀+电) 击杀合计 ÷ 总击杀数",
        "note": "花活七项之和占比，同一杀可同时满足多项（不去重）。"},
    # ---- 团队系 ----
    "team_dmg_rpr": {"label": "队伤/回合", "pct": False,
        "formula": "友军伤害总值 ÷ 出场回合数",
        "note": "每回合平均对队友造成的伤害。"},
    "avenged_rate": {"label": "被复仇率", "pct": True,
        "formula": "死亡后 2s 内被队友复仇的次数 ÷ 总死亡数",
        "note": "高=死在队友枪线内（队友罩得住）；低=孤军深入或断后位。"},
    "revenge_rate": {"label": "复仇率", "pct": True,
        "formula": "为队友完成的复仇次数 ÷ 队友死亡总次数",
        "note": "机会口径：队友每死一次都是一次复仇机会，看你去没去。"},
    "jame_index": {"label": "保枪率(Jame)", "pct": True,
        "formula": "团队输掉且你存活的回合数 ÷ 团队输掉的回合数",
        "note": "不战而退指数。可能冤枉断后位——存活≠不作为（断后时队友全送也判存活）。"},
}

BOARD_DEFS: dict[str, dict[str, str]] = {
    "donor": {"title": "💸 发枪金主（价值）", "formula": "Σ 发枪价值（$，绝对值）",
              "note": "唯一保留的绝对值榜（用户 v4 特批：价值=养队含金量）。场次多天然金额大——比意愿请看慷慨率榜。"},
    "free_pickup": {"title": "🤙 舔包王（每回合）", "formula": "白嫖枪总次数 ÷ 总回合数",
                    "note": "用户裁决 v5：除总回合数，场次多不占便宜；括号内为总次数。"},
}
# 其余榜单与同名指标口径一致（vulture/generous/poor_hero/whiff/eco/snipe/stolen/
# team_dmg/clutch/flags/jame/rebel/showoff/pure_eco），前端直接引用 METRIC_DEFS。


def funlab_report(stack: tuple[int, ...] | None = None,
                  dates: tuple[str, ...] | None = None) -> dict:
    """Return the merged report for the given filters (memoized per key)."""
    global _report, _report_key
    scan = _scan_all()
    key = (tuple(sorted(stack)) if stack else (), tuple(sorted(dates)) if dates else ())
    with _lock:
        if _report is None or _report_key != key:
            _report = _merge(scan, stack, dates)
            _report_key = key
    return _report


def invalidate_funlab() -> None:
    global _report, _report_key, _scan
    with _lock:
        _report = None
        _report_key = None
        _scan = None


def _demo_date(filename: str) -> str | None:
    """YYYYMMDD from the 5E filename (g161-20260902… / g161-n-20260902…).
    WMPVP numeric filenames (92069433…) match \d{8} too but carry no date —
    only trust g161-prefixed names."""
    if not filename.startswith("g161"):
        return None
    m = _DATE_RE.search(filename)
    return m.group(1) if m else None


def _scan_all() -> dict:
    """Expensive pass: per-demo per-player vectors + lineup/date metadata.

    Computed under the module lock (Phase S): the previous lock-outside
    pattern let an invalidate landing mid-scan get overwritten by the stale
    result — every other web memo computes inside its lock.
    """
    global _scan
    if _scan is not None:
        return _scan
    with _lock:
        if _scan is not None:  # double-checked: another thread won the race
            return _scan
        _scan = _scan_locked()
        return _scan


def _scan_locked() -> dict:
    from cs_analyzer.analysis.library import scan_demos
    from cs_analyzer.analysis.regulars import compute_regulars
    from cs_analyzer.web import runtime
    from cs_analyzer.web.store import list_demos

    cache_dir = runtime.cache().cache_dir
    meta = {d["demo_hash"]: d for d in list_demos(cache_dir)}

    def work(demo) -> dict:
        result = runtime.analyze_module(demo, "funlab")
        return {
            "demo_hash": demo.metadata.demo_hash,
            "players": result.players,
        }

    per_demo = scan_demos(cache_dir, work)

    # date + five_e flag per demo, from the filename
    entries: list[dict] = []
    five_e_player_sets: list[tuple[str, set[str]]] = []
    for e in per_demo:
        fn = meta.get(e["demo_hash"], {}).get("filename", "")
        date = _demo_date(fn)
        sids = {p["steamid"] for p in e["players"]}
        entry = {
            "demo_hash": e["demo_hash"], "players": e["players"],
            "filename": fn, "date": date,
            "is_five_e": fn.startswith("g161-"),
            "player_ids": sids,
        }
        entries.append(entry)
        if entry["is_five_e"]:
            five_e_player_sets.append((e["demo_hash"], sids))

    # regulars: >=3 appearances across the 5E set (single definition,
    # analysis.regulars — teamplay/lineups share it)
    regulars = compute_regulars(dict(five_e_player_sets))

    # lineup size per demo = how many regulars were in the match
    for e in entries:
        e["lineup_n"] = len(e["player_ids"] & regulars)

    dates = sorted({e["date"] for e in entries if e["date"]})
    out = {"entries": entries, "regulars": regulars, "dates": dates}
    return out


_SUM_FIELDS = [
    ("kills", "kills"), ("lives", "lives"), ("rounds", "rounds"),
    ("snipe_kills", "snipe_kills"), ("stolen_from", "stolen_from"),
    ("eco_frag_opponent", "eco_frags"), ("eco_rounds_played", "eco_rounds_played"),
    ("eco_frag_self", "eco_frag_self"),
    ("whiff_lives", "whiff_lives"), ("traded_deaths", "traded_deaths"),
    ("avenges", "avenges"), ("teammate_deaths", "teammate_deaths"),
    ("wallbang", "wallbang"), ("thrusmoke", "thrusmoke"),
    ("noscope", "noscope"), ("blind", "blind"), ("air", "air"),
    ("knife", "knife"), ("taser", "taser"),
    ("clutch_kills", "clutch_kills"),
    ("drops_made", "drops_made"), ("drops_value", "drops_value"),
    ("drops_poor", "drops_poor"), ("drops_received", "drops_received"),
    ("drops_value_received", "drops_value_received"),
    ("drops_wasted", "drops_wasted"), ("drops_profitable", "drops_profitable"),
    ("free_pickups", "free_pickups"), ("awp_kills", "awp_kills"),
    ("own_spend", "own_spend"), ("team_lost_rounds", "team_lost_rounds"),
    ("survived_losses", "survived_losses"), ("multi_rounds", "multi_rounds"),
    ("rebel_rounds", "rebel_rounds"), ("rebel_wins", "rebel_wins"),
    ("rebel_kills", "rebel_kills"), ("dist_n", "dist_n"),
    ("showoff_rounds", "showoff_rounds"), ("pure_eco_rounds", "pure_eco_rounds"),
]


def _merge(scan: dict, stack: tuple[int, ...] | None, dates: tuple[str, ...] | None) -> dict:
    selected = []
    for e in scan["entries"]:
        if stack and e["lineup_n"] not in stack:
            continue
        if dates and e["date"] not in dates:
            continue
        selected.append(e)

    merged: dict[str, dict] = {}
    for e in selected:
        for p in e["players"]:
            sid = p["steamid"]
            m = merged.setdefault(sid, {"steamid": sid, "name": p["name"],
                                        "demos": set(),
                                        "team_dmg": 0.0, "dist_sum": 0.0,
                                        "max_dist_m": 0.0, "dist_n": 0})
            m["demos"].add(e["demo_hash"])
            for src, dst in _SUM_FIELDS:
                m[dst] = m.get(dst, 0) + p.get(src, 0)
            m["team_dmg"] += p.get("team_dmg", 0.0)
            m["dist_sum"] += p.get("dist_sum", 0.0)
            m["dist_n"] += p.get("dist_n", 0)
            m["max_dist_m"] = max(m["max_dist_m"], p.get("max_dist_m", 0.0))

    players_out = []
    gated = 0
    for m in merged.values():
        m["demos_n"] = len(m["demos"])
        del m["demos"]
        if m["demos_n"] < MIN_DEMOS:
            gated += 1
            continue
        k = max(m["kills"], 1)
        lv = max(m["lives"], 1)
        eco_r = max(m["eco_rounds_played"], 1)
        rounds = max(m["rounds"], 1)
        flags_total = sum(m[x] for x in ("wallbang", "thrusmoke", "noscope",
                                         "blind", "air", "knife", "taser"))
        players_out.append({
            "steamid": m["steamid"], "name": m["name"], "demos": m["demos_n"],
            "kills": m["kills"], "lives": m["lives"], "rounds": m["rounds"],
            "drops_made": m["drops_made"], "drops_value": m["drops_value"],
            "drop_generosity": round(m["drops_value"] / max(m["own_spend"], 1), 3),
            "drop_poor_share": round(m["drops_poor"] / max(m["drops_made"], 1), 3),
            "drop_profit_rate": round(m["drops_profitable"] / max(m["drops_made"], 1), 3),
            "drops_received": m["drops_received"],
            "drops_value_received": m["drops_value_received"],
            "vulture_rate": round(m["drops_value_received"] /
                                  max(m["own_spend"] + m["drops_value_received"], 1), 3),
            "drop_waste_rate": round(m["drops_wasted"] / max(m["drops_received"], 1), 3),
            "free_pickups": m["free_pickups"],
            "free_pickup_rate": round(m["free_pickups"] /
                                      max(m["drops_received"] + m["free_pickups"], 1), 3),
            "free_pickup_pr": round(m["free_pickups"] / rounds, 4),
            "eco_frag_rate": round(m["eco_frags"] / k, 3),
            "eco_hard_rate": round(m["eco_frag_self"] / eco_r, 3),
            "whiff_rate": round(m["whiff_lives"] / lv, 3),
            "snipe_rate": round(m["snipe_kills"] / k, 3),
            "stolen_rate": round(m["stolen_from"] / max(m["kills"] + m["stolen_from"], 1), 3),
            "clutch_freq": round(m["clutch_kills"] / rounds, 3),
            "multi_rate": round(m["multi_rounds"] / rounds, 3),
            "avg_dist_m": round(m["dist_sum"] / max(m["dist_n"], 1), 1),
            "max_dist_m": m["max_dist_m"],
            "awp_rate": round(m["awp_kills"] / k, 3),
            "wallbang_rate": round(m["wallbang"] / k, 3),
            "thrusmoke_rate": round(m["thrusmoke"] / k, 3),
            "noscope_rate": round(m["noscope"] / k, 3),
            "blind_rate": round(m["blind"] / k, 3),
            "air_rate": round(m["air"] / k, 3),
            "knife_rate": round(m["knife"] / k, 3),
            "flags_total": flags_total,
            "flags_rate": round(flags_total / k, 3),
            "team_dmg_rpr": round(m["team_dmg"] / rounds, 2),
            "avenged_rate": round(m["traded_deaths"] / lv, 3),
            "revenge_rate": round(m["avenges"] / max(m["teammate_deaths"], 1), 3),
            "trade_balance": m["avenges"] - m["traded_deaths"],
            "jame_index": round(m["survived_losses"] / max(m["team_lost_rounds"], 1), 3),
            "rebel_rate": round(m["rebel_rounds"] / eco_r, 3),
            "rebel_win_rate": round(m["rebel_wins"] / max(m["rebel_rounds"], 1), 3),
            "rebel_kills": m["rebel_kills"],
            "rebel_rounds": m["rebel_rounds"],
            "showoff_rate": round(m["showoff_rounds"] / eco_r, 3),
            "showoff_rounds": m["showoff_rounds"],
            "pure_eco_rate": round(m["pure_eco_rounds"] / eco_r, 3),
        })
    players_out.sort(key=lambda p: -p["kills"])

    def by(key):
        rows = [p for p in players_out if p["kills"] >= 10]
        return sorted(rows, key=lambda x: x[key], reverse=True)[:10]

    # lineup distribution of the selected demos (for the filter chips)
    lineup_counts: dict[int, int] = defaultdict(int)
    for e in selected:
        lineup_counts[e["lineup_n"]] += 1

    return {
        "generated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "gate": {"min_demos": MIN_DEMOS, "players_total": len(merged), "gated": gated},
        "selected_demos": len(selected),
        "lineup_counts": {str(k): v for k, v in sorted(lineup_counts.items())},
        "dates": scan["dates"],
        "players": players_out,
        # v5 口径审计：指标口径字典随 API 下发，前端面板/轴提示/榜单统一引用
        "metric_defs": METRIC_DEFS,
        "board_defs": BOARD_DEFS,
        "boards": {
            "donor": by("drops_value"),
            "vulture": by("vulture_rate"),
            "generous": by("drop_generosity"),
            "poor_hero": by("drop_poor_share"),
            "whiff": by("whiff_rate"),
            "eco": by("eco_frag_rate"),
            "snipe": by("snipe_rate"),
            "stolen": by("stolen_rate"),
            "team_dmg": by("team_dmg_rpr"),
            "clutch": by("clutch_freq"),
            "flags": by("flags_rate"),
            "jame": by("jame_index"),
            "rebel": by("rebel_rate"),
            # v5 用户裁决：舔包王榜按白嫖频率（每回合）排序，绝对次数进 tooltip
            "free_pickup": by("free_pickup_pr"),
            "showoff": by("showoff_rate"),
            "pure_eco": by("pure_eco_rate"),
        },
    }
