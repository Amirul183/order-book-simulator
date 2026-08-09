"""
feeds/market_data.py

Utilities to format and publish market data from the order book.
Think of this as the "market data feed" layer — takes raw book state
and formats it into something consumable by UIs, APIs, analytics, etc.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.order_book import OrderBook
from core.trade import Trade


def l1_snapshot(book: OrderBook) -> Dict[str, Any]:
    """Best bid and ask only (Level 1 data)."""
    return {
        "symbol": book.symbol,
        "best_bid": book.best_bid(),
        "best_ask": book.best_ask(),
        "spread": book.spread(),
        "mid_price": book.mid_price(),
    }


def l2_snapshot(book: OrderBook, levels: int = 5) -> Dict[str, Any]:
    """Full depth snapshot up to N levels (Level 2 data)."""
    return book.depth_snapshot(levels=levels)


def format_trade_tape(trades: List[Trade], last_n: int = 20) -> List[Dict]:
    """
    Returns the most recent trades as a list of dicts.
    'Tape' is exchange jargon for the stream of executed trades.
    """
    recent = trades[-last_n:] if len(trades) > last_n else trades
    return [
        {
            "trade_id": t.trade_id,
            "price": t.price,
            "quantity": t.quantity,
            "value": round(t.value(), 4),
            "timestamp_ns": t.timestamp,
        }
        for t in reversed(recent)   # newest first
    ]


def order_imbalance(book: OrderBook) -> float:
    """
    A simple measure of buy vs sell pressure.
    Positive = more bid volume, negative = more ask volume.
    Range: -1 to +1

    This is a real metric used in market microstructure research.
    """
    snap = book.depth_snapshot(levels=10)
    bid_vol = sum(qty for _, qty in snap["bids"])
    ask_vol = sum(qty for _, qty in snap["asks"])
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total
