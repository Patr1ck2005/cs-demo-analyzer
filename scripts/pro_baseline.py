# -*- coding: utf-8 -*-
"""Phase D3a: pro reference baseline collector (bo3.gg public stats API).

D1 verdict (HANDOFF §14): bo3.gg's stats API is public and carries REAL
per-player data (steam64 pairing, per-map splits, six-month aggregates) —
while the demo FILES on that CDN are gone. So the reference baseline ships
in two layers:
  - stats layer (this file, works today): per-player aggregates from bo3.gg
  - demo layer (scripts/pro_fetch.py): needs the user's FACEIT API key

Rate-limit reality (measured): bo3.gg serves literal `null` bodies when a
client hammers the numeric-id endpoints; the by-SLUG endpoints are served
fresh. So this collector walks by slug and sleeps between calls.

CLI:  python scripts/pro_baseline.py s1mple m0nesy donk
Store: output/pro_baseline.json
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://bo3.gg/api/v1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
OUT = Path("output/pro_baseline.json")
TIMEOUT = 30
SLEEP_S = 8.0  # bo3 rate-limit: short sleeps → literal `null` bodies for ~1min


def _get_json(url: str) -> dict | list:
    for attempt in range(3):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d is not None:
            return d
        time.sleep(10.0 * (attempt + 1))  # cooldown then retry
    return None


def _get_stats(slug_or_id: str, kind: str) -> dict | list | None:
    """GET {BASE}/players/{slug}/{kind}; bo3 returns literal `null` when
    rate-limited — _get_json retries with cooldowns, final None = miss."""
    return _get_json(f"{BASE}/players/{slug_or_id}/{kind}")


def collect_player(nickname: str) -> dict | None:
    p = _get_json(f"{BASE}/players/{nickname.lower()}")
    if not isinstance(p, dict) or p.get("nickname", "").lower() != nickname.lower():
        print(f"  [{nickname}] not found on bo3.gg", file=sys.stderr)
        return None
    out = {
        "nickname": p["nickname"], "bo3_id": p["id"],
        "team_id": p.get("team_id"), "country_id": p.get("country_id"),
        "six_month_rating": p.get("six_month_avg_rating"),
        "maps": {}, "general": None, "accuracy": None,
    }
    time.sleep(SLEEP_S)
    g = _get_stats(nickname.lower(), "general_stats")
    if isinstance(g, dict):
        out["general"] = {
            "games": g.get("games_count"), "wins": g.get("games_won_count"),
            "matches": g.get("matches_count"), "rounds": g.get("rounds_count"),
            "kills": g.get("kills_sum"), "deaths": g.get("deaths_sum"),
            "assists": g.get("assists_sum"), "damage": g.get("damage_sum"),
        }
    time.sleep(SLEEP_S)
    acc = _get_stats(nickname.lower(), "accuracy_stats")
    if isinstance(acc, list):
        total_hits = sum(a.get("hits_sum", 0) for a in acc)
        head = next((a.get("hits_sum", 0) for a in acc
                     if (a.get("hit_group") or "").lower() == "head"), 0)
        out["accuracy"] = {"hits_total": total_hits, "headshots": head,
                           "hs_pct": round(head / total_hits * 100, 1) if total_hits else None}
    time.sleep(SLEEP_S)
    maps = _get_stats(nickname.lower(), "map_stats")
    if isinstance(maps, list):
        for m in maps:
            slug = m.get("map_name") or "?"
            out["maps"][slug] = {
                "maps_count": m.get("maps_count"),
                "rating": m.get("avg_player_rating"),
                "avg_kills": m.get("avg_kills"),
                "avg_damage": m.get("avg_damage"),
                "win_rate": m.get("win_rate"),
            }
    return out


def collect(nicknames: list[str]) -> dict:
    players = {}
    for nick in nicknames:
        data = collect_player(nick)
        if data:
            players[nick] = data
            g = data.get("general") or {}
            print(f"  [{nick}] maps={len(data['maps'])} games={g.get('games')} "
                  f"rating6m={data['six_month_rating']}")
        time.sleep(SLEEP_S)
    doc = {
        "source": "bo3.gg public stats API (demo files unavailable — see HANDOFF §14)",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "players": players,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT)
    return doc


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("nicknames", nargs="+", help="bo3.gg player slugs")
    args = ap.parse_args()
    doc = collect(args.nicknames)
    print(f"saved {OUT} with {len(doc['players'])} players")
