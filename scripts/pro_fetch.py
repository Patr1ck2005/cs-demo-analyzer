# -*- coding: utf-8 -*-
"""Phase D2: FACEIT ladder demo fetcher (needs a free API key to run).

Protocol (verified 2026-09-06 against open.faceit.com, see HANDOFF section 14):
  1. GET /data/v4/players?nickname={nick}            -> player_id
  2. GET /data/v4/players/{pid}/history?game=cs2     -> match ids (ladder/matchmaking)
  3. GET /data/v4/matches/{match_id}                 -> demo_url (FACEIT CDN, real .dem)
  4. GET {demo_url}                                   -> demo file (no auth needed)

Usage:
  python scripts/pro_fetch.py --nickname s1mple --count 10 [--key FACEIT_KEY | env FACEIT_API_KEY]

Every demo is saved to demos/pro/ and immediately parse-checked with the
existing parser (D2 acceptance: <10% parse failures).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "demos" / "pro"
API = "https://open.faceit.com/data/v4"
UA = "CsDemoAnalyzer/0.1 (local-first demo analyzer)"


def _get_json(path: str, key: str) -> dict:
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": UA,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        return True
    except OSError as e:
        print(f"  download failed: {e}", file=sys.stderr)
        if dest.exists():
            dest.unlink()
        return False


def fetch_player_demos(nickname: str, count: int, key: str, *, game: str = "cs2") -> list[Path]:
    """Download the newest ``count`` FINISHED matches' demos for one player."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    p = _get_json(f"/players?nickname={urllib.parse.quote(nickname)}", key)
    pid = p["player_id"]
    print(f"[{nickname}] player_id={pid} ({p.get('country')})")

    hist = _get_json(f"/players/{pid}/history?game={game}&limit={min(count, 100)}", key)
    items = [i for i in hist.get("items", []) if i.get("status") == "FINISHED"]
    print(f"[{nickname}] {len(items)} finished matches in history window")

    got: list[Path] = []
    for item in items:
        if len(got) >= count:
            break
        mid = item["match_id"]
        m = _get_json(f"/matches/{mid}", key)
        demo_url = m.get("demo_url")
        if not demo_url:
            print(f"  {mid}: no demo_url, skip")
            continue
        fname = demo_url.rsplit("/", 1)[-1]
        dest = OUT_DIR / fname
        if dest.exists() and dest.stat().st_size > 1_000_000:
            print(f"  {fname}: already present")
            got.append(dest)
            continue
        print(f"  {fname}: downloading...")
        if _download(demo_url, dest):
            # parse-check with the existing analyzer (acceptance gate)
            check = subprocess.run(
                [sys.executable, "-m", "cs_analyzer.cli", "info", str(dest)],
                capture_output=True, timeout=300)
            ok = check.returncode == 0
            manifest[fname] = {
                "player": nickname, "match_id": mid, "demo_url": demo_url,
                "map": (m.get("results") or {}).get("map", {}).get("name", ""),
                "date": m.get("started_at"), "parse_ok": ok,
                "bytes": dest.stat().st_size,
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
            got.append(dest)
            time.sleep(2)  # rate limit courtesy
    return got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nickname", required=True)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--key", default=os.environ.get("FACEIT_API_KEY", ""))
    ap.add_argument("--game", default="cs2")
    args = ap.parse_args()
    if not args.key:
        print("FACEIT API key required: --key or FACEIT_API_KEY env.\n"
              "Free key: faceit.com -> Developers -> create app.", file=sys.stderr)
        return 2
    files = fetch_player_demos(args.nickname, args.count, args.key, game=args.game)
    print(f"[{args.nickname}] {len(files)} demo(s) ready")
    return 0


if __name__ == "__main__":
    import urllib.parse
    import subprocess
    sys.exit(main())
