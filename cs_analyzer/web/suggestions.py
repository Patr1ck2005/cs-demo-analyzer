"""练习建议合成层 (复盘教练线 M2, 2026-09-12).

Zero new analysis and zero memo reads: a pure text mapping from the
``player_profile()`` dims (single source, computed once by the route) into
suggestion items. Verdicts are the profile's own; this layer only adds the
drill sentence per (dim, verdict) from ``DRILL_TEMPLATES`` (E3 口径行:
wording is a low-risk iteration surface, not per-row approved). Evidence
always travels with the suggestion (the dim anchor, raw numbers) so any
future renderer swap — e.g. a local LLM rewriting the drill prose — keeps
every claim traceable to the same evidence line.

v1 dimension set (approved 2026-09-12): duel / aim / loss / utility / eco.
``normal`` and ``na`` dims produce no suggestion (nothing to act on).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Suggestion:
    key: str        # dim key (duel/aim/loss/utility/eco) — M3 focus hint
    label: str
    status: str     # strong | weak
    evidence: str   # the profile dim anchor (raw numbers, always shown)
    drill: str      # drill sentence from DRILL_TEMPLATES


DRILL_TEMPLATES: dict[str, dict[str, str]] = {
    "duel": {
        "weak": "对枪比模型预期差——回看生涯页对枪矩阵里胜率最低的几个对手，"
                "专练该交战距离段（死斗/预瞄图按距离分段练）。",
        "strong": "对枪超预期——保持当前接敌习惯，注意把对枪优势转化成首杀交换。",
    },
    "aim": {
        "weak": "急停下开火占比偏低——开火前先停稳：aim_botz/死斗强制"
                "「停-开火」节奏每天 10 分钟，两周后回看本页数字。",
        "strong": "急停纪律好于库中绝大多数选手——保持，留意移动扫射坏习惯回潮。",
    },
    "loss": {
        "weak": "败回合高度集中于单一失利模式——在对局「复盘」Tab 按该标签"
                "连看 5 个败回合（一键定位回放器），找出重复出现的决策点。",
    },
    "utility": {
        "weak": "闪光价值/投掷低于库中位——挑 2-3 个本图常用闪光点位练熟"
                "（道具专题页有全库落点热力参考），先保证队友受盲时间。",
        "strong": "道具产出高于库中位——保持，并把闪光配合固定给常一起打的队友。",
    },
    "eco": {
        "weak": "eco 局输出低于库中位——检查 eco 局站位是否过度保枪："
                "eco 局也要抢接敌位，输出机会随站位而来。",
        "strong": "eco 局仍能稳定输出——保持，但别为 eco 数据放弃必要的保枪。",
    },
}


def suggestions_from_profile(profile: dict) -> list[Suggestion]:
    """Map profile dims → suggestions (strong/weak only, evidence carried)."""
    out: list[Suggestion] = []
    for d in profile.get("dims", []):
        status = d.get("verdict")
        if status not in ("strong", "weak"):
            continue
        drill = DRILL_TEMPLATES.get(d.get("key", ""), {}).get(status)
        if drill is None:
            continue
        out.append(Suggestion(key=d["key"], label=d.get("label", d["key"]),
                              status=status, evidence=d.get("anchor", ""),
                              drill=drill))
    return out
