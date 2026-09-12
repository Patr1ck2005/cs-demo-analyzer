"""结论合成层 (复盘提升包 B1/A2, 2026-09-10).

Zero new analysis: reads existing module results (win_probability,
loss_attribution) plus cross-library memos (duel/aim/loss/utilitylab,
peek-only) and turns them into rule-based conclusions with data anchors.
Every claim carries its evidence (n=, interval, baseline); insufficient
sample → verdict "na" (诚实灰显). Rules implement the approved 口径表
(复盘提升包计划, 2026-09-10) — thresholds live in the constants below.

U1 contract: duel/aim/loss boards are peek-only (warm memo or the
dimension degrades to "数据未就绪"); utilitylab reads the T1 snapshot
(same as /api/utilitylab.json). Nothing here ever scans the library.
"""
from __future__ import annotations

# ---- 口径表 thresholds (approved 2026-09-10) ----
ADV_SWING_MIN = 0.35   # R1: 峰值→回合结束前 p 摆幅下限
ADV_PEAK_MIN = 0.85    # R1: 优势峰值下限（一度 ≥85% 仍输）
ADV_START_MIN = 0.60   # R2: 开局优势下限（装备/人数优势局失守）
R3_TAG_KEYS = ("lost_clutch", "untraded")  # R3: 复盘必查的失利标签
LOSS_TOP_SHARE = 0.25  # 选手失利主标签占比门槛
LOSS_MIN_ROUNDS = 5    # 选手失利主标签的最少败回合数
AIM_N_MIN = 1000       # stopped_fire_rate 的开火数样本门槛
AIM_DELTA = 0.05       # 急停下开火 vs 库中位的判定带宽
UTIL_THROWS_MIN = 3    # 道具维度投掷数门槛（utilitylab "少"惯例同源）
UTIL_RATIO = 1.2       # 闪光价值/投掷 vs 库中位的判定带宽（±20%）
KEY_ROUNDS_CAP = 3     # 关键回合上限

_RULE_PRIORITY = {"本该赢却输": 0, "优势局失守": 1, "失利模式命中": 2}


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    mid = s[n // 2]
    if n % 2 == 0:
        return (s[n // 2 - 1] + mid) / 2
    return mid


def match_conclusions(
    demo,
    *,
    winprob=None,
    lossattr=None,
    oos_t: dict[tuple[int, int], float] | None = None,
    duel_board=None,
    aim_rep=None,
    loss_rep=None,
    util_rep=None,
    funlab_rep=None,
) -> dict:
    """B1: per-match key rounds + per-player improvement points.

    `oos_t` maps (round, tick) → T-view win prob from the LOO memo; when
    absent the in-sample curve is used and `curve_source` says so.
    """
    from cs_analyzer.web import runtime
    from cs_analyzer.web.winprob_loo import loo_memo_peek

    reg = demo.regular_rounds
    t_score = reg[-1].t_score if reg else 0
    ct_score = reg[-1].ct_score if reg else 0
    if t_score > ct_score:
        loser = "CT"
    elif ct_score > t_score:
        loser = "T"
    else:
        loser = None

    out: dict = {
        "loser_side": loser,
        "curve_source": "insample",
        "key_rounds": [],
        "improvements": [],
        "notes": {},
    }
    if loser is None:
        out["notes"]["tie"] = "比分相同，败方视角不可判定"
        return out

    if winprob is None:
        winprob = runtime.analyze_module(demo, "win_probability")
    if lossattr is None:
        lossattr = runtime.analyze_module(demo, "loss_attribution")

    if oos_t is None:
        memo = loo_memo_peek()
        entry = (memo or {}).get("demos", {}).get(demo.metadata.demo_hash)
        oos_t = {}
        by_pos = (memo or {}).get("oos_curves", {}).get(
            demo.metadata.demo_hash, {}).get("by_pos", {})
        if entry:
            for key, p in by_pos.items():
                rn_s, tk_s, s_s = key.split(":")
                if int(s_s) == 1:  # T-view only — same merge as the chart API
                    oos_t[(int(rn_s), int(tk_s))] = float(p)
    if oos_t:
        out["curve_source"] = "oos"

    loss_by_round: dict[int, list[str]] = {}
    if lossattr is not None:
        for r in lossattr.rounds:
            if r.get("loser_side") == loser:
                loss_by_round[r["round"]] = list(r.get("tags", []))

    # ---- per-round advantage series (loser perspective) ----
    cands: list[dict] = []
    if winprob is not None:
        for snaps in winprob.rounds:  # T-view, per round
            if not snaps:
                continue
            pts = sorted(
                (s.tick, (oos_t or {}).get((s.round, s.tick), s.p_win))
                for s in snaps)
            adv = [p if loser == "T" else 1.0 - p for _, p in pts]
            won = (snaps[0].outcome == 1) if loser == "T" \
                else (snaps[0].outcome == 0)
            cands.append({
                "round": snaps[0].round,
                "adv_max": max(adv), "adv_start": adv[0], "adv_end": adv[-1],
                "lost": not won,
                "tags": loss_by_round.get(snaps[0].round, []),
            })

    def rule1(c: dict) -> float | None:
        if not (c["lost"] and c["adv_max"] >= ADV_PEAK_MIN):
            return None
        swing = c["adv_max"] - c["adv_end"]
        return swing if swing >= ADV_SWING_MIN else None

    def rule2(c: dict) -> float | None:
        if c["lost"] and c["adv_start"] >= ADV_START_MIN:
            return c["adv_start"]
        return None

    def rule3(c: dict) -> float | None:
        hits = [t for t in c["tags"] if t in R3_TAG_KEYS]
        return 1.0 if (c["lost"] and hits) else None

    picked: dict[int, dict] = {}
    for name, fn in (("本该赢却输", rule1), ("优势局失守", rule2),
                     ("失利模式命中", rule3)):
        scored = []
        for c in cands:
            score = fn(c)
            if score is not None:
                scored.append((score, c))
        scored.sort(key=lambda x: (-x[0], x[1]["round"]))
        for score, c in scored:
            if len(picked) >= KEY_ROUNDS_CAP:
                break
            if c["round"] in picked:
                continue
            c = dict(c, rule=name, score=score)
            picked[c["round"]] = c
    key_rounds = sorted(picked.values(), key=lambda c: c["round"])
    for c in key_rounds:
        if c["rule"] == "本该赢却输":
            c["sentence"] = (f"优势峰值 {_fmt_pct(c['adv_max'])} → 仍丢分 · "
                             f"峰谷摆幅 {_fmt_pct(c['score'])}")
        elif c["rule"] == "优势局失守":
            c["sentence"] = f"开局优势 {_fmt_pct(c['adv_start'])} 仍丢分"
        else:
            hits = [t for t in c["tags"] if t in R3_TAG_KEYS]
            c["sentence"] = "命中标签：" + "、".join(hits)
    out["key_rounds"] = [
        {k: c[k] for k in ("round", "rule", "sentence", "tags", "adv_max",
                           "adv_start", "adv_end")}
        for c in key_rounds
    ]

    # ---- per-player improvement points (weak dims, ≤2 each) ----
    # key "points" (not "items" — p.items resolves to dict.items() in Jinja)
    for p in demo.players:
        prof = player_profile(p.steamid, name=p.name, duel_board=duel_board,
                              aim_rep=aim_rep, loss_rep=loss_rep,
                              util_rep=util_rep, funlab_rep=funlab_rep)
        points = prof["weak_items"][:2]
        if points:
            out["improvements"].append({"name": p.name, "points": points})
    return out


def player_profile(
    sid: str,
    name: str | None = None,
    *,
    duel_board=None,
    aim_rep=None,
    loss_rep=None,
    util_rep=None,
    funlab_rep=None,
) -> dict:
    """A2: four-dimension strength profile + B1 improvement phrasing.

    M2 (E0-E4 口径行, 2026-09-12 approved): fifth dimension 「eco 局表现」 —
    eco_hard_rate (kills per own eco round, opportunity-normalised) EB
    interval vs the library median, duel-dim shape (interval contains the
    baseline → normal). eco_frag_rate (share of kills vs eco opponents) is
    context-only in the anchor, never a verdict (E2). Zero new numeric
    constants: the interval comes from the R3 stats layer, the median from
    the gated funlab rows.

    Each dimension → {key, label, verdict(strong/normal/weak/na), value,
    anchor}; `weak_items` / `strong_items` carry the human sentences with
    data anchors. A cold memo → verdict "na" with 数据未就绪.
    """
    dims: list[dict] = []

    # ---- duel: context-adjusted diff vs model expectation ----
    from cs_analyzer.web import duel_data

    board = duel_board if duel_board is not None else duel_data.duel_peek()
    row = next((x for x in (board or {}).get("players", [])
                if x["steamid"] == sid), None) if board else None
    if row is None:
        dims.append({"key": "duel", "label": "对枪", "verdict": "na",
                     "value": None,
                     "anchor": "对枪样本不足或数据未就绪"})
    elif row["conf"]["gated"]:
        dims.append({"key": "duel", "label": "对枪", "verdict": "na",
                     "value": None,
                     "anchor": f"对枪 n={row['n']} < {row['conf'].get('gate_n', 20)}，灰显"})
    else:
        lo, hi, diff, n = row["conf"]["lo"], row["conf"]["hi"], row["diff"], row["n"]
        if diff is None:
            dims.append({"key": "duel", "label": "对枪", "verdict": "na",
                         "value": None, "anchor": "无留一期望样本"})
        elif lo > 0:
            dims.append({
                "key": "duel", "label": "对枪", "verdict": "strong",
                "value": diff, "anchor": f"超预期差 +{diff * 100:.1f}pt（n={n}）",
                "strong_item": f"对枪比模型预期强 +{diff * 100:.1f}pt（n={n}，区间 [{lo * 100:.0f}%, {hi * 100:.0f}%] 不含 0）"})
        elif hi < 0:
            dims.append({
                "key": "duel", "label": "对枪", "verdict": "weak",
                "value": diff, "anchor": f"超预期差 {diff * 100:.1f}pt（n={n}）",
                "weak_item": f"对枪比模型预期差 {diff * 100:.1f}pt（n={n}，区间上界 {hi * 100:.0f}% 仍为负）"})
        else:
            dims.append({"key": "duel", "label": "对枪", "verdict": "normal",
                         "value": diff,
                         "anchor": f"超预期差 {diff * 100:+.1f}pt（n={n}，区间含 0）"})

    # ---- aim: stopped-fire rate vs library median ----
    from cs_analyzer.web import aim_data

    rep = aim_rep if aim_rep is not None else aim_data.aim_peek()
    rows = (rep or {}).get("players", [])
    row = next((x for x in rows if x["steamid"] == sid), None) if rows else None
    med = _median([x["stopped_fire_rate"] for x in rows
                   if x.get("stopped_fire_rate") is not None
                   and x.get("n_shots", 0) >= AIM_N_MIN]) if rows else None
    if (row is None or row.get("stopped_fire_rate") is None
            or row.get("n_shots", 0) < AIM_N_MIN or med is None):
        dims.append({"key": "aim", "label": "枪法纪律", "verdict": "na",
                     "value": None,
                     "anchor": f"急停下开火样本不足（需 ≥{AIM_N_MIN} 发）或数据未就绪"})
    else:
        rate = row["stopped_fire_rate"]
        if rate >= med + AIM_DELTA:
            dims.append({
                "key": "aim", "label": "枪法纪律", "verdict": "strong",
                "value": rate, "anchor": f"急停下开火 {_fmt_pct(rate)} vs 库中位 {_fmt_pct(med)}",
                "strong_item": f"急停下开火 {_fmt_pct(rate)}，高于库中位 {_fmt_pct(med)}（n={row['n_shots']} 发）"})
        elif rate <= med - AIM_DELTA:
            dims.append({
                "key": "aim", "label": "枪法纪律", "verdict": "weak",
                "value": rate, "anchor": f"急停下开火 {_fmt_pct(rate)} vs 库中位 {_fmt_pct(med)}",
                "weak_item": f"急停下开火 {_fmt_pct(rate)}，低于库中位 {_fmt_pct(med)}（n={row['n_shots']} 发）"})
        else:
            dims.append({"key": "aim", "label": "枪法纪律", "verdict": "normal",
                         "value": rate,
                         "anchor": f"急停下开火 {_fmt_pct(rate)} ≈ 库中位 {_fmt_pct(med)}"})

    # ---- loss mode: top tag share of the player's lost rounds ----
    from cs_analyzer.web import loss_data

    loss_rep_ = loss_rep if loss_rep is not None else loss_data.loss_peek()
    prow = next((x for x in (loss_rep_ or {}).get("players", [])
                 if x["steamid"] == sid), None) if loss_rep_ else None
    if prow is None or not prow.get("lost_rounds"):
        dims.append({"key": "loss", "label": "失利模式", "verdict": "na",
                     "value": None,
                     "anchor": "败回合样本不足或数据未就绪"})
    else:
        n_lost = prow["lost_rounds"]
        top_tag, top_count = max(prow["tags"].items(), key=lambda kv: kv[1])
        top_share = top_count / n_lost
        if top_share >= LOSS_TOP_SHARE and n_lost >= LOSS_MIN_ROUNDS:
            label = loss_data.TAG_DEFS.get(top_tag, top_tag).split("：")[0]
            dims.append({
                "key": "loss", "label": "失利模式", "verdict": "weak",
                "value": top_share,
                "anchor": f"{label} 占 {top_share:.0%}（{top_count}/{n_lost} 败回合）",
                "weak_item": f"失利主模式：{label} 出现在 {top_share:.0%} 的败回合"
                             f"（{top_count}/{n_lost}）"})
        else:
            dims.append({"key": "loss", "label": "失利模式", "verdict": "normal",
                         "value": None,
                         "anchor": f"无占比 ≥{LOSS_TOP_SHARE:.0%} 的失利主标签"
                                   f"（{n_lost} 败回合）"})

    # ---- utility: flash value per throw vs library median ----
    from cs_analyzer.web import utilitylab_data

    rep = util_rep if util_rep is not None else utilitylab_data.utilitylab_report()
    flashers = (rep or {}).get("flashers", [])
    row = next((x for x in flashers if x["steamid"] == sid), None)
    med = _median([x["value_per_throw"] for x in flashers
                   if x.get("throws", 0) >= UTIL_THROWS_MIN]) if flashers else None
    if row is None or row.get("throws", 0) < UTIL_THROWS_MIN or med is None:
        dims.append({"key": "utility", "label": "道具", "verdict": "na",
                     "value": None,
                     "anchor": f"投掷 <{UTIL_THROWS_MIN} 次或数据未就绪"})
    else:
        vpt = row["value_per_throw"]
        if vpt >= med * UTIL_RATIO:
            dims.append({
                "key": "utility", "label": "道具", "verdict": "strong",
                "value": vpt, "anchor": f"闪光价值/投掷 {vpt:.2f} vs 库中位 {med:.2f}",
                "strong_item": f"闪光价值/投掷 {vpt:.2f}，高于库中位 {med:.2f}（{row['throws']} 投）"})
        elif vpt <= med / UTIL_RATIO:
            dims.append({
                "key": "utility", "label": "道具", "verdict": "weak",
                "value": vpt, "anchor": f"闪光价值/投掷 {vpt:.2f} vs 库中位 {med:.2f}",
                "weak_item": f"闪光价值/投掷 {vpt:.2f}，低于库中位 {med:.2f}（{row['throws']} 投）"})
        else:
            dims.append({"key": "utility", "label": "道具", "verdict": "normal",
                         "value": vpt,
                         "anchor": f"闪光价值/投掷 {vpt:.2f} ≈ 库中位 {med:.2f}"})

    # ---- eco (M2 E1): eco_hard_rate EB interval vs library median ----
    from cs_analyzer.web.funlab_data import funlab_peek

    rep = funlab_rep if funlab_rep is not None else funlab_peek()
    rows = (rep or {}).get("players", [])
    row = next((x for x in rows if x["steamid"] == sid), None) if rows else None
    conf = (row or {}).get("conf", {}).get("eco_hard_rate") if row else None
    med = _median([x["eco_hard_rate"] for x in rows
                   if x.get("eco_hard_rate") is not None]) if rows else None
    if (row is None or conf is None or conf.get("gated")
            or row.get("eco_hard_rate") is None or med is None):
        dims.append({"key": "eco", "label": "eco 局表现", "verdict": "na",
                     "value": None,
                     "anchor": "funlab 样本不足（≥3 场门槛）或数据未就绪"})
    else:
        rate, lo, hi, n = (row["eco_hard_rate"], conf["lo"], conf["hi"],
                           conf["n"])
        frag = row.get("eco_frag_rate")
        frag_med = _median([x["eco_frag_rate"] for x in rows
                            if x.get("eco_frag_rate") is not None])
        ctx = (f"（含金量：{frag:.0%} 击杀来自对手 eco 局，库中位 "
               f"{frag_med:.0%}）" if frag is not None and frag_med is not None
               else "")
        if hi < med:
            dims.append({
                "key": "eco", "label": "eco 局表现", "verdict": "weak",
                "value": rate,
                "anchor": f"神仙率 {rate:.2f} 杀/eco 回合 vs 库中位 {med:.2f} · {ctx}",
                "weak_item": f"eco 局输出偏低：神仙率 {rate:.2f} 杀/eco 回合，"
                             f"区间上界 {hi:.2f} 仍低于库中位 {med:.2f}（n={n} 个 eco 回合）"})
        elif lo > med:
            dims.append({
                "key": "eco", "label": "eco 局表现", "verdict": "strong",
                "value": rate,
                "anchor": f"神仙率 {rate:.2f} 杀/eco 回合 vs 库中位 {med:.2f} · {ctx}",
                "strong_item": f"eco 局仍能稳定输出：神仙率 {rate:.2f} 杀/eco 回合，"
                               f"区间下界 {lo:.2f} 高于库中位 {med:.2f}（n={n} 个 eco 回合）"})
        else:
            dims.append({"key": "eco", "label": "eco 局表现", "verdict": "normal",
                         "value": rate,
                         "anchor": f"神仙率 {rate:.2f} 杀/eco 回合 ≈ 库中位 "
                                   f"{med:.2f}（区间含中位） · {ctx}"})

    return {
        "steamid": sid, "name": name, "dims": dims,
        "weak_items": [d["weak_item"] for d in dims if "weak_item" in d],
        "strong_items": [d["strong_item"] for d in dims if "strong_item" in d],
    }

