"""
benchmarks/bench_throughput.py

Standalone benchmark script — doesn't need pytest, just run it directly.
Measures raw order processing throughput and latency distribution.

Usage:
    python benchmarks/bench_throughput.py
    python benchmarks/bench_throughput.py --n 1000000
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# make sure we can import from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.metrics import LatencyTracker
from core.matching_engine import MatchingEngine
from feeds.synthetic import SyntheticFeed


def run(n: int, seed: int, symbol: str):
    engine = MatchingEngine(symbol=symbol)
    feed = SyntheticFeed(symbol=symbol, seed=seed)
    tracker = LatencyTracker(window_size=min(n, 100_000))

    print(f"\nWarming up with 10,000 orders...")
    for order in feed.stream(n=10_000):
        engine.process(order)

    # reset for the real run
    engine = MatchingEngine(symbol=symbol)
    feed = SyntheticFeed(symbol=symbol, seed=seed + 1)
    tracker = LatencyTracker(window_size=min(n, 100_000))

    print(f"Running benchmark: {n:,} orders\n")
    t_start = time.perf_counter()

    for order in feed.stream(n=n):
        t0 = time.perf_counter_ns()
        engine.process(order)
        t1 = time.perf_counter_ns()
        tracker.record(t1 - t0)

    elapsed = time.perf_counter() - t_start
    throughput = n / elapsed

    lat = tracker.summary()
    print(f"{'-'*45}")
    print(f"  {'Orders processed':<25} {n:>15,}")
    print(f"  {'Wall time':<25} {elapsed:>14.3f}s")
    print(f"  {'Throughput':<25} {throughput:>12,.0f} /s")
    print(f"  {'Trades executed':<25} {len(engine.trades):>15,}")
    print(f"{'-'*45}")
    print(f"  {'Avg latency':<25} {lat['avg_ns']:>12.1f} ns")
    print(f"  {'p50 latency':<25} {lat['p50_ns']:>15} ns")
    print(f"  {'p95 latency':<25} {lat['p95_ns']:>15} ns")
    print(f"  {'p99 latency':<25} {lat['p99_ns']:>15} ns")
    print(f"{'-'*45}")
    print(f"  {'Best bid':<25} {engine.book.best_bid()}")
    print(f"  {'Best ask':<25} {engine.book.best_ask()}")
    print(f"  {'Spread':<25} {engine.book.spread()}")
    print()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100_000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--symbol", default="AAPL")
    args = p.parse_args()
    run(n=args.n, seed=args.seed, symbol=args.symbol)
