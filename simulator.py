"""
simulator.py

Main entry point. Two modes:
  1. `api`       — starts the FastAPI server with the live dashboard (default)
  2. `benchmark` — runs a throughput/latency benchmark and prints results

Usage:
    python simulator.py                          # starts API + dashboard on localhost:8000
    python simulator.py --mode benchmark --n 500000
    python simulator.py --mode api --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from analytics.metrics import LatencyTracker, MarketMetrics
from api.routes import register_engine, router
from api.ws import _broadcast_worker, push_snapshot, push_trade, ws_router
from config import API_HOST, API_PORT, SYMBOL
from core.matching_engine import MatchingEngine
from feeds.synthetic import SyntheticFeed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Symbols to boot on startup
# ------------------------------------------------------------------

ACTIVE_SYMBOLS = ["AAPL", "TSLA", "NVDA", "BTC-USD"]
SEED_ORDERS_PER_SYMBOL = 500   # pre-warm each book so it's not empty on first load


# ------------------------------------------------------------------
# Lifespan — replaces the deprecated @app.on_event("startup")
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: boot one matching engine per symbol, pre-seed each book,
             register engines, and start the WebSocket broadcast workers.
    Shutdown: nothing special needed — uvicorn handles the rest.
    """
    logger.info("Starting up order book simulator...")

    broadcast_tasks = []

    for symbol in ACTIVE_SYMBOLS:
        engine = MatchingEngine(symbol=symbol)

        # pre-seed the book so it's not empty when users first connect
        feed = SyntheticFeed(symbol=symbol, seed=hash(symbol) % 10_000)
        for order in feed.stream(n=SEED_ORDERS_PER_SYMBOL):
            engine.process(order)

        # wire up WebSocket push callbacks
        def make_snapshot_cb(sym: str, eng: MatchingEngine):
            """Closure so each symbol gets its own callback."""
            def _cb(trade):
                push_trade(sym, trade)
                push_snapshot(sym, eng)
            return _cb

        engine.on_trade(make_snapshot_cb(symbol, engine))

        # register for REST routes
        register_engine(symbol, engine)

        # start the per-symbol broadcast worker
        task = asyncio.create_task(
            _broadcast_worker(symbol),
            name=f"broadcast-{symbol}",
        )
        broadcast_tasks.append(task)

        logger.info(f"  [{symbol}] engine ready | {engine.book}")

    logger.info(f"All {len(ACTIVE_SYMBOLS)} engines online. Dashboard → http://{API_HOST}:{API_PORT}/")

    yield  # app runs here

    # cancel background tasks on shutdown
    for task in broadcast_tasks:
        task.cancel()
    logger.info("Shutdown complete.")


# ------------------------------------------------------------------
# FastAPI app setup
# ------------------------------------------------------------------

app = FastAPI(
    title="Order Book Simulator",
    description=(
        "A high-performance in-memory limit order book and matching engine. "
        "Supports limit and market orders with price-time priority (FIFO) matching. "
        "Real-time updates streamed over WebSocket."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Allow all origins for the local demo.
# In production you'd lock this down to your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(ws_router)

# Serve the static dashboard at the root
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    """Serve the trading terminal dashboard."""
    index = static_dir / "index.html"
    if not index.exists():
        return {"error": "Dashboard not found. Run the server and check static/index.html."}
    return FileResponse(str(index))


# ------------------------------------------------------------------
# Benchmark mode
# ------------------------------------------------------------------

def run_benchmark(n: int, symbol: str, seed: int):
    print(f"\n{'='*60}")
    print(f"  Benchmark: {n:,} orders | symbol={symbol} | seed={seed}")
    print(f"{'='*60}")

    engine = MatchingEngine(symbol=symbol)
    feed = SyntheticFeed(symbol=symbol, seed=seed)
    tracker = LatencyTracker()
    market = MarketMetrics()

    engine.on_trade(market.record_trade)

    snapshot_every = max(1, n // 100)
    processed = 0

    t_start = time.perf_counter()

    for order in feed.stream(n=n):
        t0 = time.perf_counter_ns()
        engine.process(order)
        t1 = time.perf_counter_ns()
        tracker.record(t1 - t0)
        processed += 1

        if processed % snapshot_every == 0:
            market.snapshot(
                mid=engine.book.mid_price(),
                spread=engine.book.spread(),
                trade_count=len(engine.trades),
            )

    t_elapsed = time.perf_counter() - t_start
    throughput = n / t_elapsed

    print(f"\nResults:")
    print(f"  Orders processed : {processed:,}")
    print(f"  Wall time        : {t_elapsed:.3f}s")
    print(f"  Throughput       : {throughput:,.0f} orders/sec")
    print(f"  Trades executed  : {len(engine.trades):,}")
    print(f"\nLatency (per order):")
    lat = tracker.summary()
    print(f"  avg  : {lat['avg_ns']:.1f} ns")
    print(f"  p50  : {lat['p50_ns']} ns")
    print(f"  p95  : {lat['p95_ns']} ns")
    print(f"  p99  : {lat['p99_ns']} ns")
    print(f"\nMarket:")
    print(f"  VWAP          : {market.vwap():.4f}")
    print(f"  Total volume  : {market._total_volume:,}")
    print(f"  Final spread  : {engine.book.spread()}")
    print(f"  Best bid/ask  : {engine.book.best_bid()} / {engine.book.best_ask()}")
    print(f"{'='*60}\n")

    try:
        from analytics.visualizer import plot_summary
        plot_summary(market, symbol=symbol)
    except Exception as e:
        print(f"[plot skipped: {e}]")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Order Book Simulator")
    p.add_argument("--mode", choices=["api", "benchmark"], default="api")
    p.add_argument("--host", default=API_HOST)
    p.add_argument("--port", type=int, default=API_PORT)
    p.add_argument("--symbol", default=SYMBOL)
    p.add_argument("--n", type=int, default=100_000, help="number of orders (benchmark mode)")
    p.add_argument("--seed", type=int, default=42, help="random seed (benchmark mode)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.mode == "benchmark":
        run_benchmark(n=args.n, symbol=args.symbol, seed=args.seed)
    else:
        print(f"\nStarting Order Book Simulator")
        print(f"  Dashboard  : http://{args.host}:{args.port}/")
        print(f"  API docs   : http://{args.host}:{args.port}/api/docs\n")
        uvicorn.run("simulator:app", host=args.host, port=args.port, reload=False)
