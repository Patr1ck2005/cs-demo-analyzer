"""Platform demo importer (Phase Y 2026-09-07).

Scans the platform download directories in configs/demo_sources.yaml for
*.zip packages, extracts the inner .dem, dedupes by CONTENT hash against
demos/ (the zip container never hash-equals its payload — Y1 lesson), and
copies genuinely new demos into demos/. Unreadable (truncated) zips are
skipped with a report, following the 5E precedent.

Usage:
    python scripts/platform_import.py [--dry-run]

Exit code 0 = at least the scan ran; failures are reported per-zip.
After importing, parse via the web (POST /system/import) or the CLI batch.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
DEMOS_DIR = REPO / "demos"
SOURCES_YAML = REPO / "configs" / "demo_sources.yaml"
_CHUNK = 1 << 20


def _sha_stream(fh) -> str:
    h = hashlib.sha256()
    for part in iter(lambda: fh.read(_CHUNK), b""):
        h.update(part)
    return h.hexdigest()


def _file_sha(p: Path) -> str:
    with p.open("rb") as fh:
        return _sha_stream(fh)


def _load_sources() -> list[dict]:
    import yaml

    raw = yaml.safe_load(SOURCES_YAML.read_text(encoding="utf-8")) or {}
    out = []
    for name, cfg in raw.items():
        if not isinstance(cfg, dict) or not cfg.get("enabled"):
            continue
        out.append({"name": name, "path": Path(cfg["path"]),
                    "pattern": cfg.get("pattern", "*.zip"),
                    "note": cfg.get("note", "")})
    return out


def _known_hashes(demos_dir: Path) -> set[str]:
    return {_file_sha(p) for p in demos_dir.glob("*.dem")}


def _inner_dems(zp: Path) -> list[str]:
    with zipfile.ZipFile(zp) as zf:
        return [n for n in zf.namelist() if n.lower().endswith(".dem")]


def import_all(dry_run: bool = False) -> int:
    if not DEMOS_DIR.exists():
        DEMOS_DIR.mkdir()
    known = _known_hashes(DEMOS_DIR)
    print(f"demos/ 现有 {len(known)} 个 demo（内容哈希索引）")
    summary = {"imported": [], "exists": [], "bad": []}

    for src in _load_sources():
        if not src["path"].is_dir():
            print(f"[{src['name']}] 目录不存在，跳过: {src['path']}")
            continue
        print(f"[{src['name']}] 扫描 {src['path']}")
        for zp in sorted(src["path"].glob(src["pattern"])):
            try:
                inners = _inner_dems(zp)
            except Exception as exc:  # noqa: BLE001 — truncated EOCD etc.
                print(f"  坏包跳过 {zp.name}: {exc}")
                summary["bad"].append(zp.name)
                continue
            for inner in inners:
                try:
                    with zipfile.ZipFile(zp) as zf:
                        with zf.open(inner) as fh:
                            digest = _sha_stream(fh)
                except Exception as exc:  # noqa: BLE001
                    print(f"  读取失败 {zp.name}/{inner}: {exc}")
                    summary["bad"].append(f"{zp.name}/{inner}")
                    continue
                target = DEMOS_DIR / Path(inner).name
                if digest in known or target.exists():
                    print(f"  已存在（内容一致）{target.name} ← {zp.name}")
                    summary["exists"].append(target.name)
                    continue
                if dry_run:
                    print(f"  [dry-run] 将导入 {target.name} ← {zp.name}")
                    summary["imported"].append(target.name)
                    continue
                shutil.copyfileobj(
                    zipfile.ZipFile(zp).open(inner), target.open("wb"))
                known.add(digest)
                print(f"  导入 {target.name} ← {zp.name}")
                summary["imported"].append(target.name)

    print(f"\n=== 汇总：新导入 {len(summary['imported'])} · "
          f"已存在 {len(summary['exists'])} · 损坏/跳过 {len(summary['bad'])}")
    for n in summary["imported"]:
        print(f"  + {n}")
    for n in summary["bad"]:
        print(f"  ! {n}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="只报告将要导入的内容，不写 demos/")
    args = ap.parse_args()
    return import_all(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
