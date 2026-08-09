"""
core/order.py

Defines the basic building blocks: OrderSide, OrderType, and Order itself.
This is a pure data module — no matching logic lives here, just structure
and a few guard clauses to catch obvious mistakes early.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

__all__ = ["OrderSide", "OrderType", "OrderStatus", "Order"]


class OrderSide(Enum):
    BID = "bid"   # buyer
    ASK = "ask"   # seller


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"
    CANCEL = "cancel"


class OrderStatus(Enum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class Order:
    """
    Represents a single order in the book.

    price is None for market orders — we fill them at whatever's available.
    quantity tracks the *original* size; remaining_qty shrinks as fills happen.
    """

    side: OrderSide
    order_type: OrderType
    quantity: int
    symbol: str = "AAPL"
    price: Optional[float] = None     # None for market orders

    # auto-generated fields
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: int = field(default_factory=time.perf_counter_ns)   # nanoseconds
    remaining_qty: int = field(init=False)
    status: OrderStatus = field(init=False, default=OrderStatus.OPEN)

    def __post_init__(self):
        self.remaining_qty = self.quantity

        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("limit orders require a price")

        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")

    def fill(self, qty: int):
        """Reduce remaining qty by qty. Updates status accordingly."""
        if qty > self.remaining_qty:
            # shouldn't happen if the matching engine is doing its job
            raise ValueError(f"trying to fill {qty} but only {self.remaining_qty} left")
        self.remaining_qty -= qty
        if self.remaining_qty == 0:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    def is_active(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    def __repr__(self):
        price_str = f"@{self.price:.2f}" if self.price is not None else "@MKT"
        return (
            f"Order({self.order_id} {self.side.value.upper()} "
            f"{self.remaining_qty}/{self.quantity} {price_str} [{self.status.value}])"
        )
