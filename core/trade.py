"""
core/trade.py

A trade is what happens when a bid and ask match.
Immutable once created — trades are facts, not opinions.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Trade:
    """
    Records an execution between two orders.

    frozen=True because once a trade happens you don't get to change it.
    That's... kind of the whole point of a trade.
    """

    buyer_order_id: str
    seller_order_id: str
    price: float
    quantity: int
    symbol: str

    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: int = field(default_factory=time.perf_counter_ns)

    def value(self) -> float:
        """Notional value of the trade."""
        return self.price * self.quantity

    def __repr__(self):
        return (
            f"Trade({self.trade_id} {self.symbol} "
            f"{self.quantity}@{self.price:.2f} "
            f"buy={self.buyer_order_id} sell={self.seller_order_id})"
        )
