"""
api/ws.py

WebSocket endpoint for real-time order book and trade streaming.

Each client connects to /ws/{symbol} and immediately starts receiving
JSON frames whenever the book state changes (after every order processed).

Frame format:
    {
        "type": "snapshot",          # "snapshot" | "trade" | "error"
        "symbol": "AAPL",
        "bids": [[price, qty], ...], # top 10 levels, high -> low
        "asks": [[price, qty], ...], # top 10 levels, low -> high
        "spread": 0.05,
        "mid_price": 100.0,
        "imbalance": 0.12,
        "best_bid": 99.97,
        "best_ask": 100.02,
        "stats": { ... }
    }

Trade frames look like:
    {
        "type": "trade",
        "symbol": "AAPL",
        "trade_id": "a1b2c3d4",
        "price": 100.0,
        "quantity": 50,
        "value": 5000.0,
        "timestamp_ns": 1234567890
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from feeds.market_data import l2_snapshot, order_imbalance

logger = logging.getLogger(__name__)

ws_router = APIRouter()

# per-symbol sets of connected WebSocket clients
_subscribers: Dict[str, Set[WebSocket]] = {}

# per-symbol asyncio queues — the matching engine pushes updates here,
# the broadcaster coroutine reads and fans out to all subscribers
_queues: Dict[str, asyncio.Queue] = {}


def get_queue(symbol: str) -> asyncio.Queue:
    """Get (or lazily create) the broadcast queue for a symbol."""
    if symbol not in _queues:
        _queues[symbol] = asyncio.Queue(maxsize=2048)
    return _queues[symbol]


def push_snapshot(symbol: str, engine) -> None:
    """
    Called from the matching engine's trade callback (sync context).
    Builds a snapshot frame and puts it on the queue non-blocking.
    If the queue is full we drop the frame — a slow consumer doesn't block matching.
    """
    try:
        snap = l2_snapshot(engine.book, levels=10)
        frame = {
            "type": "snapshot",
            "symbol": symbol,
            "bids": snap["bids"],
            "asks": snap["asks"],
            "spread": snap.get("spread"),
            "mid_price": snap.get("mid_price"),
            "imbalance": round(order_imbalance(engine.book), 4),
            "best_bid": engine.book.best_bid(),
            "best_ask": engine.book.best_ask(),
            "stats": engine.stats(),
        }
        queue = get_queue(symbol)
        queue.put_nowait(frame)
    except asyncio.QueueFull:
        pass  # slow client — drop this frame, next one will arrive shortly
    except Exception as e:
        logger.warning(f"[ws] push_snapshot error for {symbol}: {e}")


def push_trade(symbol: str, trade) -> None:
    """Push a trade execution event to the symbol's broadcast queue."""
    try:
        frame = {
            "type": "trade",
            "symbol": symbol,
            "trade_id": trade.trade_id,
            "price": trade.price,
            "quantity": trade.quantity,
            "value": round(trade.value(), 4),
            "timestamp_ns": trade.timestamp,
        }
        get_queue(symbol).put_nowait(frame)
    except asyncio.QueueFull:
        pass
    except Exception as e:
        logger.warning(f"[ws] push_trade error for {symbol}: {e}")


async def _broadcast_worker(symbol: str) -> None:
    """
    Background coroutine: reads frames off the queue and fans them
    out to every subscriber for this symbol. Runs for the lifetime of the app.
    """
    queue = get_queue(symbol)
    while True:
        frame = await queue.get()
        payload = json.dumps(frame)
        dead: Set[WebSocket] = set()

        subs = _subscribers.get(symbol, set())
        for ws in list(subs):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)

        # clean up disconnected clients
        subs -= dead


@ws_router.websocket("/ws/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str) -> None:
    """
    WebSocket handler. Each client:
    1. Connects and is added to the subscriber set for the symbol
    2. Receives a welcome snapshot immediately
    3. Receives live frames whenever the book changes
    4. Is cleaned up on disconnect
    """
    symbol = symbol.upper()
    await websocket.accept()

    if symbol not in _subscribers:
        _subscribers[symbol] = set()
    _subscribers[symbol].add(websocket)

    logger.info(f"[ws] client connected → {symbol} (total: {len(_subscribers[symbol])})")

    # send an immediate snapshot so the client doesn't stare at a blank screen
    from api.routes import get_engine_for_symbol
    from feeds.market_data import format_trade_tape
    try:
        engine = get_engine_for_symbol(symbol)
        snap = l2_snapshot(engine.book, levels=10)
        # include last 30 trades so the tape isn't empty on first load
        recent_trades = format_trade_tape(engine.trades, last_n=30)
        welcome = {
            "type": "snapshot",
            "symbol": symbol,
            "bids": snap["bids"],
            "asks": snap["asks"],
            "spread": snap.get("spread"),
            "mid_price": snap.get("mid_price"),
            "imbalance": round(order_imbalance(engine.book), 4),
            "best_bid": engine.book.best_bid(),
            "best_ask": engine.book.best_ask(),
            "stats": engine.stats(),
            "recent_trades": recent_trades,  # pre-populate the tape
        }
        await websocket.send_text(json.dumps(welcome))
    except Exception as e:
        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))

    try:
        # Keep the connection alive — we only receive pings/close from the client
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _subscribers.get(symbol, set()).discard(websocket)
        logger.info(f"[ws] client disconnected ← {symbol} (remaining: {len(_subscribers.get(symbol, set()))})")
