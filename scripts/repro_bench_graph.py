#!/usr/bin/env python3
"""Bench graph endpoints + O(E^2) vs O(E) edge dedup on a CKbase DB.

Usage:
  python scripts/repro_bench_graph.py --db /path/.llmwikify.db
  python scripts/repro_bench_graph.py --base-url http://127.0.0.1:8765
  python scripts/repro_bench_graph.py --db ... --base-url ... --concurrency 10
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def bench_algo(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT source_page, target_page FROM page_links").fetchall()
    n = len(rows)

    t0 = time.perf_counter()
    edges_old: list[dict] = []
    for src, tgt in rows:
        if not any(
            e["source"] == src and e["target"] == tgt and e["type"] == "wikilink"
            for e in edges_old
        ):
            edges_old.append(
                {"source": src, "target": tgt, "type": "wikilink", "weight": 1}
            )
    t_old = time.perf_counter() - t0

    t0 = time.perf_counter()
    edges_new: list[dict] = []
    seen: dict[tuple[str, str, str], dict] = {}
    for src, tgt in rows:
        key = (src, tgt, "wikilink")
        e = seen.get(key)
        if e is not None:
            e["weight"] += 1
        else:
            e = {"source": src, "target": tgt, "type": "wikilink", "weight": 1}
            seen[key] = e
            edges_new.append(e)
    t_new = time.perf_counter() - t0

    return {
        "links": n,
        "unique_edges": len(edges_new),
        "old_e2_s": round(t_old, 3),
        "new_e_s": round(t_new, 4),
        "speedup": round(t_old / t_new, 1) if t_new > 0 else None,
        "edge_count_match": len(edges_old) == len(edges_new),
    }


def _get(url: str, timeout: float = 120.0) -> tuple[int, float, int]:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, time.perf_counter() - t0, len(body)
    except urllib.error.HTTPError as e:
        return e.code, time.perf_counter() - t0, 0


def bench_http(base: str, path: str, repeats: int = 3) -> dict:
    times = []
    status = None
    size = 0
    for _ in range(repeats):
        status, dt, size = _get(base.rstrip("/") + path)
        times.append(dt)
    return {
        "path": path,
        "status": status,
        "bytes": size,
        "seconds": [round(t, 3) for t in times],
        "median_s": round(statistics.median(times), 3),
    }


def bench_concurrent_status(base: str, n: int = 10) -> dict:
    url = base.rstrip("/") + "/api/wiki/status"
    times: list[float] = []

    def one() -> float:
        _, dt, _ = _get(url)
        return dt

    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = [pool.submit(one) for _ in range(n)]
        for f in as_completed(futs):
            times.append(f.result())
    times.sort()
    return {
        "n": n,
        "seconds": [round(t, 3) for t in times],
        "p50_s": round(statistics.median(times), 3),
        "p95_s": round(times[max(0, int(len(times) * 0.95) - 1)], 3),
        "max_s": round(times[-1], 3),
    }


def bench_http_with_graph_inflight(base: str, status_n: int = 10) -> dict:
    """Fire graph request, then status load — measures event-loop blocking."""
    import threading

    graph_result: dict = {}
    done = threading.Event()

    def graph_worker() -> None:
        graph_result.update(bench_http(base, "/api/wiki/graph", repeats=1))
        done.set()

    th = threading.Thread(target=graph_worker)
    th.start()
    time.sleep(0.05)  # let graph start first
    status = bench_concurrent_status(base, n=status_n)
    th.join(timeout=180)
    return {"graph": graph_result, "status_during_graph": status}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, help="path to .llmwikify.db")
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--skip-algo", action="store_true")
    ap.add_argument("--skip-http", action="store_true")
    ap.add_argument("--skip-inflight", action="store_true")
    args = ap.parse_args()

    out: dict = {}
    if not args.skip_algo:
        if not args.db:
            raise SystemExit("--db required unless --skip-algo")
        print("== algorithm microbench ==")
        algo = bench_algo(args.db)
        out["algo"] = algo
        print(json.dumps(algo, indent=2))

    if not args.skip_http:
        print("== http endpoints ==")
        http = {}
        for p in ("/api/health", "/api/wiki/status", "/api/wiki/graph", "/api/wiki/graph_analyze"):
            http[p] = bench_http(args.base_url, p, repeats=args.repeats)
            print(json.dumps(http[p]))
        out["http"] = http

    if not args.skip_inflight:
        print("== status while graph in flight ==")
        inflight = bench_http_with_graph_inflight(args.base_url, status_n=args.concurrency)
        out["inflight"] = inflight
        print(json.dumps(inflight, indent=2))

    Path("repro_bench_result.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\nWrote repro_bench_result.json")


if __name__ == "__main__":
    main()
