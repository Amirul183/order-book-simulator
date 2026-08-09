# High-Performance In-Memory Order Book Simulator

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![WebSocket](https://img.shields.io/badge/WebSocket-real--time-6200ea?style=flat-square)](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-pytest-yellow?style=flat-square&logo=pytest)](tests/)

A fully functional **limit order book and matching engine** built in Python — the core piece of infrastructure that powers every financial exchange. Submit limit and market orders via a REST API or a live trading terminal, and watch them match in real time over WebSocket.

Built to understand **market microstructure** from first principles: how exchanges maintain order books, why price-time priority matters, and what it actually takes to build a low-latency matching system.

---

## Live Dashboard

Open `http://localhost:8000/` after starting the server to get a full trading terminal:

- 📗 **Order Book** — live bid/ask depth with volume bars and flash animations
- 📋 **Trade Tape** — every executed trade streams in via WebSocket
- 📊 **Imbalance Bar** — real-time buy vs. sell pressure indicator
- ⚡ **Latency Stats** — avg, p50, p95, p99 nanosecond latency per order
- 🔁 **Symbol Switcher** — AAPL · TSLA · NVDA · BTC-USD (separate engine per symbol)
- 📤 **Order Form** — submit limit or market orders directly from the UI

---

## Features

| Category | What's included |
|---|---|
| **Matching** | Price-time priority (FIFO), limit & market orders, partial fills |
| **Data structures** | `SortedDict` per side (O(log N) insert), `deque` per price level (O(1) FIFO) |
| **Performance** | Nanosecond-precision latency tracking, rolling percentile windows |
| **API** | FastAPI REST endpoints + WebSocket real-time streaming |
| **Multi-symbol** | Independent engine per symbol, all running concurrently |
| **Feed** | Gaussian random-walk synthetic order generator |
| **Analytics** | VWAP, market metrics, matplotlib depth charts + summary plots |
| **Benchmark mode** | Throughput + latency report in CLI |
| **Tests** | 15+ pytest unit tests covering all matching edge cases |

---

## Architecture

```
orderbook-simulator/
│
├── core/
│   ├── order.py             # Order dataclass (Limit, Market, Cancel)
│   ├── order_book.py        # Two-sided book: SortedDict + deque per level
│   ├── matching_engine.py   # Price-time priority matching + event system
│   └── trade.py             # Immutable trade record (frozen dataclass)
│
├── feeds/
│   ├── synthetic.py         # Gaussian random-walk order generator
│   └── market_data.py       # L1/L2 snapshots, trade tape formatter, imbalance
│
├── analytics/
│   ├── metrics.py           # LatencyTracker (rolling percentiles), MarketMetrics, VWAP
│   └── visualizer.py        # Depth chart + summary plots (matplotlib)
│
├── api/
│   ├── routes.py            # FastAPI REST endpoints (multi-symbol)
│   └── ws.py                # WebSocket handler + per-symbol broadcast queues
│
├── static/
│   └── index.html           # Live trading terminal dashboard
│
├── tests/                   # pytest unit tests
├── benchmarks/              # Standalone throughput benchmark
├── simulator.py             # Main entry point (server + benchmark CLI)
├── config.py                # Tick size, symbol, API defaults
├── pyproject.toml           # Modern Python packaging
└── requirements.txt         # Direct dependencies
```

### Why these data structures?

| Layer | Structure | Reason |
|---|---|---|
| Price levels | `SortedDict` | O(log N) insert/delete, O(1) best-price access |
| Orders at a level | `collections.deque` | O(1) append + popleft = FIFO naturally |
| Cancel lookup | `dict` (order_id → price) | O(1) to locate the order's price level |

**Alternative considered**: `heapq` for price levels — works for insertions but lazy deletion for cancels requires tombstones and is messy. `SortedDict` is cleaner and fast enough for Python.

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/yourusername/orderbook-simulator.git
cd orderbook-simulator

# 2. Create a virtual environment and install
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

# 3. Start the server
python simulator.py
```

Then open **http://localhost:8000/** for the live dashboard, or **http://localhost:8000/api/docs** for the interactive API docs.

---

## API Reference

All endpoints accept and return JSON. The `symbol` parameter defaults to `AAPL` on every route.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Live trading terminal dashboard |
| `POST` | `/order` | Submit a new limit or market order |
| `DELETE` | `/order/{id}?symbol=AAPL` | Cancel an open order |
| `GET` | `/orderbook?symbol=AAPL&levels=10` | Top N bid/ask levels + spread + imbalance |
| `GET` | `/orderbook/l1?symbol=AAPL` | Best bid/ask only (L1 data) |
| `GET` | `/trades?symbol=AAPL&last_n=50` | Recent trade tape |
| `GET` | `/stats?symbol=AAPL` | Engine stats (throughput, latency, trade count) |
| `GET` | `/symbols` | List of active symbols |
| `GET` | `/health` | Health check |
| `WS` | `/ws/{symbol}` | Real-time order book + trade stream |

### Submit a limit buy order

```bash
curl -X POST http://localhost:8000/order \
  -H "Content-Type: application/json" \
  -d '{"side": "bid", "order_type": "limit", "price": 149.50, "quantity": 100, "symbol": "AAPL"}'
```

```json
{
  "order_id": "a3f1bc2e",
  "status": "open",
  "trades_executed": 0,
  "message": "order processed — 0 trade(s) executed"
}
```

### WebSocket frame format

Connect to `ws://localhost:8000/ws/AAPL` and you'll receive:

```json
{
  "type": "snapshot",
  "symbol": "AAPL",
  "bids": [[149.97, 250], [149.95, 100]],
  "asks": [[150.02, 150], [150.05, 200]],
  "spread": 0.05,
  "mid_price": 149.995,
  "imbalance": 0.12,
  "stats": { "processed": 5000, "trades_executed": 712, "avg_latency_ns": 8234.1 }
}
```

Trade events arrive separately:

```json
{
  "type": "trade",
  "symbol": "AAPL",
  "trade_id": "b2c3d4e5",
  "price": 150.0,
  "quantity": 50,
  "value": 7500.0,
  "timestamp_ns": 1234567890
}
```

---

## Benchmark Mode

```bash
python simulator.py --mode benchmark --n 500000
```

Sample output on a typical laptop:

```
============================================================
  Benchmark: 500,000 orders | symbol=AAPL | seed=42
============================================================

Results:
  Orders processed : 500,000
  Wall time        : 4.831s
  Throughput       : 103,490 orders/sec
  Trades executed  : 71,204

Latency (per order):
  avg  : 9,663.2 ns
  p50  : 7,800 ns
  p95  : 22,100 ns
  p99  : 48,300 ns
```

> **Note**: Python is not a production HFT language — C++ or Rust would be used in a real exchange. The data structures chosen here mirror what you'd use in production; the interesting part is the *logic*, not the raw numbers.

---

## Run Tests

```bash
pytest tests/ -v
```

Test coverage includes:
- Simple limit order matching
- Partial fills (both sides)
- Price priority (best price matches first)
- Time priority (FIFO within the same price level)
- Multi-level sweeps (aggressor walks through multiple price levels)
- Market orders against empty book
- No-match cases (spread too wide)
- Cancel operations

---

## What I Learned Building This

- **Price-time priority** is surprisingly elegant to implement with `deque` per price level — FIFO is literally free.
- **Order book data structures** are a classic CS trade-off: `SortedDict` wins over `heapq` specifically because cancellations are common and heap lazy-deletion gets ugly fast.
- **Nanosecond timing** in Python (`time.perf_counter_ns()`) is real but the Python call overhead itself is ~hundreds of nanoseconds, so the latency numbers are Python overhead + matching work.
- **WebSocket broadcast** at high frequency requires careful backpressure handling — a slow client shouldn't block the matching engine. The solution here is a per-symbol `asyncio.Queue` with a max size and frame-dropping on overflow.
- **FastAPI's lifespan** context manager (replacing the deprecated `@app.on_event`) is the clean way to manage startup/shutdown in modern FastAPI.

---

## Possible Extensions

- **Iceberg orders** — show a partial visible quantity, hide the rest in a reserve
- **Stop-loss / stop-limit orders** — triggered when the market price crosses a threshold
- **LOBSTER dataset replay** — replay real limit order book data from a real exchange
- **Order book heatmap** — visualize order density over time as a 2D heatmap
- **Persistent trade log** — write every trade to SQLite or Parquet
- **Cython hot path** — the `_execute_match` loop is the bottleneck; wrapping it in Cython could give a 5–10x speedup

---

## License

[MIT](LICENSE)
