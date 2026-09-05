# -*- coding: utf-8 -*-
"""Phase T2 探针：全库重算的 GIL 占用与进程池收益实测（决策依据）。

测三段：
  A. load   — parquet 加载（pyarrow，声称释放 GIL）
  B. analyze— AnalysisRunner 分析（pandas/numpy，GIL 密集）
  C. merge  — 跨场合并（纯 Python，GIL 锁死）

方法：串行基线 vs ThreadPoolExecutor(4)（现状）vs ProcessPoolExecutor(4)
（Windows spawn）。进程池只并行 A 段（demo 对象可 pickle；runner 带状态不可），
即"进程池加载 + 主进程分析"混合流水线——这是收益上界估计。

输出：JSON 到 stdout（重定向到文件再读——pwsh 管道吞 python 输出的老坑）。
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / ".cache"


def load_one(demo_hash: str):
    from cs_analyzer.cache import DemoCache

    return DemoCache(CACHE).load(demo_hash)


def analyze_one(demo):
    from cs_analyzer.analysis import AnalysisRunner
    from cs_analyzer.config import AnalysisConfig

    runner = AnalysisRunner(AnalysisConfig(enabled_modules=["basic_stats", "ratings"]))
    return runner.run(demo)


def load_and_analyze(demo_hash: str):
    """Process-pool unit: load + analyze IN the worker, ship back only a
    tiny scalar (the real design would ship small module payloads)."""
    from cs_analyzer.analysis import AnalysisRunner
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.config import AnalysisConfig

    demo = DemoCache(CACHE).load(demo_hash)
    if demo is None:
        return 0
    runner = AnalysisRunner(AnalysisConfig(enabled_modules=["basic_stats", "ratings"]))
    results = runner.run(demo)
    basic = results.get("basic_stats")
    return sum(p.kills for p in basic.players) if basic else 0


def main() -> None:
    from cs_analyzer.analysis.library import cached_demo_hashes

    hashes = cached_demo_hashes(CACHE)
    out: dict = {"n_demos": len(hashes)}

    # ---- serial baseline (load+analyze together) ----
    t0 = time.perf_counter()
    loaded = [load_one(h) for h in hashes]
    t_load = time.perf_counter() - t0
    t0 = time.perf_counter()
    results = [analyze_one(d) for d in loaded]
    t_analyze = time.perf_counter() - t0
    out["serial"] = {"load_s": round(t_load, 2), "analyze_s": round(t_analyze, 2),
                     "total_s": round(t_load + t_analyze, 2)}

    # ---- thread pool 4 (current library.py behavior) ----
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        loaded_t = list(ex.map(load_one, hashes))
    t_load_t = time.perf_counter() - t0
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        results_t = list(ex.map(analyze_one, loaded_t))
    t_analyze_t = time.perf_counter() - t0
    out["thread4"] = {"load_s": round(t_load_t, 2), "analyze_s": round(t_analyze_t, 2),
                      "total_s": round(t_load_t + t_analyze_t, 2)}

    # ---- process pool 4 (load+analyze IN worker, tiny result back) ----
    # Note: pickling ParsedDemo back to the parent OOMs (ticks ~30MB/demo) —
    # measured 2026-09-05, that failure IS a data point: any process design
    # must compute in the worker and return small payloads only.
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=4) as ex:
        probe = list(ex.map(load_and_analyze, hashes))
    t_pa = time.perf_counter() - t0
    out["proc4_worker"] = {"total_s": round(t_pa, 2),
                           "sanity_kill_sum": sum(probe),
                           "note": "load+analyze in worker, scalar result back"}

    base = out["thread4"]["total_s"]
    best = out["proc4_worker"]["total_s"]
    out["decision"] = {
        "gain_vs_thread4_pct": round((base - best) / base * 100, 1),
        "threshold_pct": 30.0,
        "verdict": "ADOPT" if (base - best) / base >= 0.30 else "REJECT",
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
