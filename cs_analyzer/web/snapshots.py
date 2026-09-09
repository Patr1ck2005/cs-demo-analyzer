"""Disk snapshots for the cross-demo memos (Phase T1 聚合快照落盘).

Every cross-demo memo (aggregate, highlight feed, teamplay, utility-lab,
map, lineups, fun-lab scan, style galaxy) rebuilds by walking the whole
parse cache — together the warmup pass costs ~175s on the 24-demo library,
paid again after every process start and every invalidate. A snapshot
persists each memo's *payload* to ``<OUT_DIR>/snapshots/<name>.json`` and
reloads it when the library fingerprint is unchanged, collapsing a warm
restart to well under a second.

Fingerprint = SHA-256 over
  - SNAPSHOT_VERSION (this file's format/logic version)
  - PARSER_VERSION (a parser bump re-parses every demo)
  - a content digest of the producer source files (analysis modules +
    web data modules) — a correctness fix must not serve stale numbers
  - the parse-cache contents: sorted (demo_hash, sha256(model.json))

Rules:
- one JSON file per memo; ``save`` is atomic (tmp + os.replace); every
  load/save error is fail-soft (missing or corrupt file = a miss)
- snapshots are written ONLY by the prewarm thread after a successful
  full rebuild (never from request paths) — the in-memory memos stay the
  single source of truth while the process is warm
- invalidates do NOT delete files: the fingerprint mismatch makes them
  inert, and the next successful rebuild overwrites them in place
- tests isolate via ``web_app.OUT_DIR`` (the snapshots dir hangs off it),
  the same monkeypatch surface favorites/ui-prefs already use
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Bump when the snapshot logic or any payload shape changes (e.g. a new
#: field in a report that restore() must map). Source-file digesting makes
#: ordinary code edits invalidate automatically; this constant is for
#: structural changes the digest cannot see.
SNAPSHOT_VERSION = 1

_write_lock = threading.Lock()

#: Snapshot items: name -> (module attribute path for payload, restore fn).
#: Populated lazily by ``_items()`` to keep module-level imports cycle-free.
SNAPSHOT_NAMES = (
    "aggregate",       # web.aggregation   (AggregateResult dataclass)
    "feed",            # web.feed_data     (list[dict])
    "teamplay",        # web.teamplay_data (dict)
    "utilitylab",      # web.utilitylab_data (dict)
    "map",             # web.mapdata       (dict)
    "lineups",         # web.lineups_data  (dict)
    "funlab_scan",     # web.funlab_data   (dict, sets encoded as lists)
    "style_map",       # web.style_map     (dict)
)

#: Producer source files hashed into the fingerprint — a correctness fix in
#: any of these must invalidate the numbers they produce (S3-style fixes
#: changed values without touching PARSER_VERSION).
_SNAPSHOT_SOURCES = (
    "analysis/__init__.py",
    "analysis/aggregate.py",
    "analysis/basic_stats.py",
    "analysis/ratings.py",
    "analysis/funlab.py",
    "analysis/teamplay.py",
    "analysis/utility_effect.py",
    "analysis/routes.py",
    "analysis/postplant.py",
    "analysis/highlights.py",
    "analysis/regulars.py",
    "analysis/util.py",
    "analysis/library.py",
    "analysis/aim_science.py",
    "analysis/loss_attribution.py",
    # S3-A1: per-demo SHARD-family producers. src8 = digest of THIS list, so
    # a change inside any of these must roll the shard dirs or stale per-demo
    # payloads survive under a fingerprint-identical rebuild (same defect
    # class as the S2-A1 merge-layer gap).
    "analysis/win_probability.py",   # winloo   shards (web/winprob_loo.py)
    "analysis/economy_ev.py",        # ev_cells shards (web/ev_data.py)
    "analysis/ratings21.py",         # rating21 shards (web/rating21_data.py)
    # S2-A1: R1 conf values (Wilson z / EB k) are computed at MERGE layer and
    # land inside the T1 snapshot payloads of lineups/map/utilitylab — a
    # stats.py change must invalidate those numbers or stale intervals
    # survive a fingerprint-identical rebuild.
    "analysis/stats.py",
    "web/aggregation.py",
    "web/feed_data.py",
    "web/teamplay_data.py",
    "web/utilitylab_data.py",
    "web/mapdata.py",
    "web/lineups_data.py",
    "web/funlab_data.py",
    "web/style_map.py",
    "web/ev_data.py",
    "web/winprob_loo.py",
    "web/aim_data.py",
    "web/loss_data.py",
    "web/rating21_data.py",
    "web/snapshots.py",
)

_src_digest_cache: str | None = None


# ---------------------------------------------------------------- fingerprint


def _source_digest() -> str:
    """Content digest of the memo-producing source files (cached per process).

    Computed once — a running server never sees its own source change, and a
    restart re-hashes ~22 small files in well under 50ms.
    """
    global _src_digest_cache
    if _src_digest_cache is not None:
        return _src_digest_cache
    pkg_root = Path(__file__).resolve().parent.parent  # .../cs_analyzer
    h = hashlib.sha256()
    for rel in _SNAPSHOT_SOURCES:
        p = pkg_root / rel
        try:
            h.update(rel.encode())
            h.update(p.read_bytes())
        except OSError:  # missing file (packaged subset) — hash the marker
            h.update(rel.encode())
            h.update(b"<missing>")
    _src_digest_cache = h.hexdigest()[:16]
    return _src_digest_cache


def _cached_demo_hashes(cache_dir: Path) -> list[str]:
    from cs_analyzer.analysis.library import cached_demo_hashes

    return cached_demo_hashes(cache_dir)


def library_fingerprint(cache_dir: Path) -> str:
    """Stable identity of (library, parser, producing code, snapshot logic)."""
    from cs_analyzer.cache import PARSER_VERSION

    h = hashlib.sha256()
    h.update(f"v{SNAPSHOT_VERSION}|parser:{PARSER_VERSION}|src:{_source_digest()}\n".encode())
    for model_json in sorted(Path(cache_dir).glob("*/model.json")):
        rel = model_json.parent.name  # demo hash = directory name
        digest = hashlib.sha256(model_json.read_bytes()).hexdigest()
        h.update(f"{rel}:{digest}\n".encode())
    return h.hexdigest()[:32]


# ------------------------------------------------------------------ payload io


def snapshots_dir(out_dir: Path) -> Path:
    """Snapshots hang off the app's OUT_DIR (tests monkeypatch that)."""
    return Path(out_dir) / "snapshots"


def load_snapshot(name: str, fingerprint: str, out_dir: Path) -> object | None:
    """Payload for ``name`` if a snapshot with a matching fingerprint exists."""
    p = snapshots_dir(out_dir) / f"{name}.json"
    try:
        env = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.exception("snapshot %s unreadable — treating as miss", name)
        return None
    if not isinstance(env, dict) or env.get("name") != name:
        return None
    if env.get("fingerprint") != fingerprint:
        return None
    return env.get("payload")


def save_snapshot(name: str, fingerprint: str, payload: object, out_dir: Path) -> bool:
    """Atomically persist one snapshot; fail-soft (an IO hiccup must never
    break the prewarm that just finished)."""
    d = snapshots_dir(out_dir)
    p = d / f"{name}.json"
    env = {
        "version": SNAPSHOT_VERSION,
        "name": name,
        "fingerprint": fingerprint,
        "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "payload": payload,
    }
    try:
        with _write_lock:
            d.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(env, ensure_ascii=False,
                                      separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, p)
        return True
    except (OSError, TypeError, ValueError):
        logger.exception("snapshot %s store failed (fail-soft)", name)
        return False


# -------------------------------------------------------- per-module adapters
#
# Every memo module exposes the same tiny pair:
#   snapshot_payload() -> JSON-able payload of the CURRENT memo (None if cold)
#   restore_snapshot(payload) -> seed the memo from a snapshot payload
# The pair lives in the owning module (it knows its dataclasses/sets);
# snapshots.py only orchestrates. funlab's scan layer carries sets, so its
# encode/decode is explicit; aggregate's dataclasses go through asdict.


def _payload_for(name: str) -> object | None:
    """Current memo payload for ``name``, or None when the memo is cold.

    None must NOT trigger a compute — saving happens on the prewarm thread
    where real steps have materialized the memos; a cold memo just means the
    step never ran (tests stub them).
    """
    from cs_analyzer.web import (
        aggregation,
        feed_data,
        funlab_data,
        lineups_data,
        mapdata,
        style_map,
        teamplay_data,
        utilitylab_data,
    )

    if name == "aggregate":
        with aggregation._lock:
            return aggregation._snapshot_payload()  # None when cold
    if name == "feed":
        with feed_data._lock:
            return feed_data._snapshot_payload()
    if name == "teamplay":
        with teamplay_data._lock:
            return teamplay_data._snapshot_payload()
    if name == "utilitylab":
        with utilitylab_data._lock:
            return utilitylab_data._snapshot_payload()
    if name == "map":
        with mapdata._lock:
            return mapdata._snapshot_payload()
    if name == "lineups":
        with lineups_data._lock:
            return lineups_data._snapshot_payload()
    if name == "funlab_scan":
        with funlab_data._lock:
            return funlab_data._snapshot_payload()
    if name == "style_map":
        with style_map._lock:
            return style_map._snapshot_payload()
    raise KeyError(name)


def _restore(name: str, payload: object) -> None:
    """Seed the module memo from a snapshot payload (under the module lock)."""
    from cs_analyzer.web import (
        aggregation,
        feed_data,
        funlab_data,
        lineups_data,
        mapdata,
        style_map,
        teamplay_data,
        utilitylab_data,
    )

    if name == "aggregate":
        aggregation.restore_snapshot(payload)
    elif name == "feed":
        feed_data.restore_snapshot(payload)
    elif name == "teamplay":
        teamplay_data.restore_snapshot(payload)
    elif name == "utilitylab":
        utilitylab_data.restore_snapshot(payload)
    elif name == "map":
        mapdata.restore_snapshot(payload)
    elif name == "lineups":
        lineups_data.restore_snapshot(payload)
    elif name == "funlab_scan":
        funlab_data.restore_scan_snapshot(payload)
    elif name == "style_map":
        style_map.restore_snapshot(payload)
    else:
        raise KeyError(name)


#: snapshot name -> warmup step name it satisfies (rest of the steps run
#: only for the misses; style_map/map/lineups have no warmup step at all).
_STEP_OF = {
    "aggregate": "aggregate",
    "feed": "highlights",
    "teamplay": "teamplay",
    "utilitylab": "utilitylab",
    "funlab_scan": "funlab",
}


# ------------------------------------------------------------------- warmup api


def restore_all(out_dir: Path, cache_dir: Path) -> list[str]:
    """Try to seed every memo from snapshots. Returns the names that hit.

    Per-item validity: one corrupt/mismatched file is a miss for that memo
    only; the warmup loop recomputes exactly the missing steps.
    """
    fp = library_fingerprint(cache_dir)
    hits: list[str] = []
    for name in SNAPSHOT_NAMES:
        payload = load_snapshot(name, fp, out_dir)
        if payload is None:
            continue
        try:
            _restore(name, payload)
            hits.append(name)
        except Exception:  # noqa: BLE001 — a bad payload must not kill warmup
            logger.exception("snapshot %s restore failed — recomputing", name)
    return hits


def save_all(out_dir: Path, cache_dir: Path) -> dict[str, bool]:
    """Persist every MATERIALIZED memo. Cold memos are skipped (never
    computed here — saving runs only after the prewarm rebuilt them).

    The fingerprint is computed fresh: if an invalidate landed mid-prewarm,
    the memos may be older than the library — in that case nothing is saved
    and the NEXT rebuild (kick) writes consistent snapshots.
    """
    fp = library_fingerprint(cache_dir)
    saved: dict[str, bool] = {}
    for name in SNAPSHOT_NAMES:
        payload = _payload_for(name)
        if payload is None:
            saved[name] = False
            continue
        saved[name] = save_snapshot(name, fp, payload, out_dir)
    return saved


def status(out_dir: Path, cache_dir: Path) -> dict:
    """Snapshot inventory for the /system performance panel."""
    fp = library_fingerprint(cache_dir)
    items: list[dict] = []
    for name in SNAPSHOT_NAMES:
        p = snapshots_dir(out_dir) / f"{name}.json"
        entry: dict = {"name": name, "exists": p.exists(), "current": False}
        if p.exists():
            try:
                env = json.loads(p.read_text(encoding="utf-8"))
                entry["current"] = env.get("fingerprint") == fp
                entry["saved_at"] = env.get("saved_at", "")
                entry["size_kb"] = round(p.stat().st_size / 1024, 1)
            except (OSError, ValueError):
                entry["current"] = False
        items.append(entry)
    return {"fingerprint": fp, "snapshots": items}


# ---------------------------------------------------------------- shard cache
#
# Phase T3 增量重算：全库快照管"重启秒开"，分片管"新 demo 只算新 demo"。
# 每个 memo 的 per-demo 产出缓存为
#   shards/<memo>/<src8>/<demo_hash>_<model8>.json
# - <src8>  = 源码摘要前 8 位：任何 producer 代码变更 → 整个目录作废（GC 清）
# - <model8>= 该 demo model.json 摘要前 8 位：重解析（PARSER bump / sweep）
#             改变内容 → 文件名不再匹配 → 自动 miss
# 分片有效性与全库指纹无关——新 demo 到来时旧 demo 的分片依然命中，
# compute 只补算缺失的 demo，然后按当前库全量合并。


def _model_tag(cache_dir: Path, demo_hash: str) -> str:
    p = Path(cache_dir) / demo_hash / "model.json"
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:8]
    except OSError:
        return "nomodel"


def _shard_dir(memo: str, out_dir: Path) -> Path:
    return Path(out_dir) / "snapshots" / "shards" / memo / _source_digest()[:8]


def load_shards(memo: str, out_dir: Path, cache_dir: Path,
                hashes: list[str]) -> tuple[dict, list[str]]:
    """({hash: payload} for valid shards, [hashes still needing compute])."""
    d = _shard_dir(memo, out_dir)
    got: dict = {}
    missing: list[str] = []
    for h in hashes:
        p = d / f"{h}_{_model_tag(cache_dir, h)}.json"
        try:
            env = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            missing.append(h)
            continue
        payload = env.get("payload") if isinstance(env, dict) else None
        if payload is None:
            missing.append(h)
        else:
            got[h] = payload
    return got, missing


def save_shard(memo: str, out_dir: Path, cache_dir: Path, demo_hash: str,
               payload: object) -> bool:
    d = _shard_dir(memo, out_dir)
    p = d / f"{demo_hash}_{_model_tag(cache_dir, demo_hash)}.json"
    env = {"version": SNAPSHOT_VERSION, "demo_hash": demo_hash, "payload": payload}
    try:
        with _write_lock:
            d.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(env, ensure_ascii=False,
                                      separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, p)
        return True
    except (OSError, TypeError, ValueError):
        logger.exception("shard %s/%s store failed (fail-soft)", memo, demo_hash[:12])
        return False


def gc_shards(out_dir: Path, cache_dir: Path) -> int:
    """Delete shard files that no longer match the current library/code —
    old src-digest directories, renamed demos, re-parsed model hashes.
    Returns the number of files removed (S1 磁盘卫生精神：残渣不留).
    """
    removed = 0
    base = Path(out_dir) / "snapshots" / "shards"
    if not base.is_dir():
        return 0
    live_src = _source_digest()[:8]
    current = {h: f"{h}_{_model_tag(cache_dir, h)}.json"
               for h in _cached_demo_hashes(cache_dir)}
    for memo_dir in base.glob("*"):
        if not memo_dir.is_dir():
            continue
        for src_dir in memo_dir.glob("*"):
            if not src_dir.is_dir():
                continue
            if src_dir.name != live_src:
                for f in src_dir.glob("*.json"):
                    try:
                        f.unlink()
                        removed += 1
                    except OSError:
                        pass
                continue
            for f in src_dir.glob("*.json"):
                if f.name not in current.values():
                    try:
                        f.unlink()
                        removed += 1
                    except OSError:
                        pass
            try:
                next(src_dir.iterdir())
            except StopIteration:
                with contextlib.suppress(OSError):
                    src_dir.rmdir()
        try:
            next(memo_dir.iterdir())
        except StopIteration:
            with contextlib.suppress(OSError):
                memo_dir.rmdir()
    return removed
