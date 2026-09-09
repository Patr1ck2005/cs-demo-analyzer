# -*- coding: utf-8 -*-
"""Phase R research probe: reproducible numbers from the real library.

Writes output/research_probe.json with:
  - aim-science calibration sanity (aim-at-damage median per demo must be
    small; a large value means the angle convention or the data is off),
  - cross-library aim-science medians per player,
  - retrofitted confidence samples from the funlab report,
  - loss-attribution tag counts per team,
  - utility execute buckets (smoke-before-contact vs round win).

Usage:  python scripts/probe_research.py [--out output/research_probe.json]
Cache-only (no .dem parsing). Materializes the aimsci/lossattr shard families
on first run (~2-4 min); subsequent runs are fast.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)

OUT_DEFAULT = Path("output/research_probe.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()

    from cs_analyzer.web import aim_data, loss_data, runtime, snapshots
    from cs_analyzer.web.funlab_data import funlab_report
    from cs_analyzer.web.utilitylab_data import utilitylab_report

    hashes = snapshots._cached_demo_hashes(runtime.cache().cache_dir)
    print(f"library: {len(hashes)} cached demos")

    # ---- merged research reports (materializes shards on first run) ----
    aim = aim_data.aim_report()
    loss = loss_data.loss_report()
    util = utilitylab_report()
    fun = funlab_report()

    # ---- aim-science calibration sanity ----
    calib = aim.get("calibrations", [])
    aim_bad = [c for c in calib
               if c.get("aim_at_damage_med_deg") is None
               or c["aim_at_damage_med_deg"] > 25.0]

    conf_samples = []
    for p in fun["players"][:5]:
        conf_samples.append({
            "player": p["name"],
            "snipe_rate": p.get("snipe_rate"),
            "snipe_conf": (p.get("conf") or {}).get("snipe_rate"),
            "drops_value_per_demo": p.get("drops_value_per_demo"),
            "donor_shrunk": p.get("shrunk_drops_value_per_demo"),
        })

    out = {
        "generated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "library_demos": len(hashes),
        "aim_calibration": {
            "n_demos_with_calib": len(calib),
            "n_suspect": len(aim_bad),
            "suspect_demos": [c.get("demo_hash", "?") for c in aim_bad][:10],
            "samples": calib[:8],
            "verdict": "OK" if not aim_bad else "REVIEW",
        },
        "aim_science_top": [
            {k: p.get(k) for k in ("name", "demos", "preaim_n", "preaim_med_deg",
                                   "preaim_lt10_rate", "counter_med_s",
                                   "counter_fast_rate", "aim_dmg_med_deg")}
            for p in aim["players"][:8]
        ],
        "loss_patterns": {"demos": loss.get("demos"), "teams": loss.get("teams")},
        "utility_exec": {
            "exec_players_top": [
                {k: e.get(k) for k in ("name", "enemy_blind_throws",
                                       "support_kills", "support_flash_rate",
                                       "late_rate", "molly_dmg_per_throw")}
                for e in util.get("exec_players", [])[:6]
            ],
            "smoke_buckets": util.get("smoke_buckets", [])[:12],
        },
        "funlab_conf_samples": conf_samples,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # ---- S3-D2: structural guard — an empty container must FAIL loudly,
    # never pass as "OK (0/0)" (the fail-soft silent-death class: T4 lesson).
    # Calibration must cover the whole library; every report container must
    # be non-empty for a non-empty library.
    problems: list[str] = []
    if not hashes:
        problems.append("library is empty (0 cached demos)")
    else:
        if len(calib) != len(hashes):
            problems.append(
                f"calibration covers {len(calib)}/{len(hashes)} demos")
        for label, container in (
            ("aim.players", aim.get("players")),
            ("loss.teams", loss.get("teams")),
            ("utility.exec_players", util.get("exec_players")),
            ("utility.smoke_buckets", util.get("smoke_buckets")),
            ("funlab.players", fun.get("players")),
        ):
            if not container:
                problems.append(f"{label} is empty")
    if problems:
        for p in problems:
            print(f"GUARD FAIL: {p}")
        print("written (for diagnosis): " + str(out_path))
        return 2

    print(f"verdict: {out['aim_calibration']['verdict']} "
          f"({len(aim_bad)}/{len(calib)} suspect)")
    print(f"written: {out_path}")
    return 0 if not aim_bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
