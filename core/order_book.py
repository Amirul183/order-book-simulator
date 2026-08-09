"""
core/order_book.py

The actual order book — two sides (bids and asks), each organized by price level.

Data structure choice:
  - SortedDict from sortedcontainers for the price levels. O(log N) insert/delete,
    O(1) best-price lookup. Tried using heapq first but managing cancellations
    with a heap is a nightmare (lazy deletion, tombstones, etc.). SortedDict is
    just cleaner for this.
  - collections.deque per price level for FIFO ordering within the same price.
    This enforces price-time priority correctly.

The book itself doesn't do matching — that's the matching engine's job.
This class is just responsible for maintaining state.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple

from sortedcontainers import SortedDict

from core.order import Order, OrderSide, OrderStatus

__all__ = ["PriceLevel", "OrderBook"]


class PriceLevel:
    """A queue of orders all sitting at the same price."""

    def __init__(self, price: float):
        self.price = price
        self.orders: deque[Order] = deque()
        self._total_qty = 0

    def add(self, order: Order):
        self.orders.append(order)
        self._total_qty += order.remaining_qty

    def remove(self, order_id: str) -> Optional[Order]:
        """Pull a specific order out by id. O(N) but cancels aren't on the hot path."""
        for i, o in enumerate(self.orders):
            if o.order_id == order_id:
                self.orders.remove(o)
                self._recalculate_qty()  # recalculate to stay accurate after removal
                return o
        return None

    def peek(self) -> Optional[Order]:
        # skip past any filled/cancelled orders at the front
        while self.orders and not self.orders[0].is_active():
            removed = self.orders.popleft()
        self._recalculate_qty()
        return self.orders[0] if self.orders else None

    @property
    def total_qty(self) -> int:
        return self._total_qty

    def update_qty(self, delta: int):
        """Called by the matching engine when a fill happens."""
        self._total_qty = max(0, self._total_qty - delta)

    def _recalculate_qty(self):
        """Recompute total_qty from scratch. Called after removes to avoid drift."""
        self._total_qty = sum(o.remaining_qty for o in self.orders if o.is_active())

    def is_empty(self) -> bool:
        return len(self.orders) == 0 or self.peek() is None

    def __len__(self):
        return len(self.orders)


class OrderBook:
    """
    Two-sided limit order book for a single instrument.

    Bids: sorted descending (highest price = best bid, index -1)
    Asks: sorted ascending (lowest price = best ask, index 0)

    SortedDict gives us log(N) operations for both sides and makes
    the best bid/ask O(1) to access.
    """

    def __init__(self, symbol: str = "AAPL"):
        self.symbol = symbol

        # bids: key = price (we negate when iterating to get descending order)
        # actually SortedDict is ascending by default, so for bids we store as
        # negative keys — that way iloc[-1] is the best (highest) bid
        self._bids: SortedDict = SortedDict()   # price -> PriceLevel
        self._asks: SortedDict = SortedDict()   # price -> PriceLevel

        # fast lookup: order_id -> (side, price) so cancels are O(1) to locate
        self._order_index: Dict[str, Tuple[OrderSide, float]] = {}

        self._order_count = 0   # total orders ever added (not just open ones)

    # ------------------------------------------------------------------
    # Adding orders
    # ------------------------------------------------------------------

    def add_limit_order(self, order: Order):
        assert order.price is not None

        if order.side == OrderSide.BID:
            key = order.price
            if key not in self._bids:
                self._bids[key] = PriceLevel(order.price)
            self._bids[key].add(order)
        else:
            key = order.price
            if key not in self._asks:
                self._asks[key] = PriceLevel(order.price)
            self._asks[key].add(order)

        self._order_index[order.order_id] = (order.side, order.price)
        self._order_count += 1

    # ------------------------------------------------------------------
    # Cancellations
    # ------------------------------------------------------------------

    def cancel_order(self, order_id: str) -> Optional[Order]:
        if order_id not in self._order_index:
            return None  # already filled or never existed

        side, price = self._order_index.pop(order_id)

        book_side = self._bids if side == OrderSide.BID else self._asks
        if price not in book_side:
            return None

        level: PriceLevel = book_side[price]
        order = level.remove(order_id)

        if order:
            order.status = OrderStatus.CANCELLED

        # clean up empty price levels — keeps the book tidy
        if level.is_empty():
            del book_side[price]

        return order

    # ------------------------------------------------------------------
    # Best prices
    # ------------------------------------------------------------------

    def best_bid(self) -> Optional[float]:
        if not self._bids:
            return None
        return self._bids.keys()[-1]   # highest price

    def best_ask(self) -> Optional[float]:
        if not self._asks:
            return None
        return self._asks.keys()[0]    # lowest price

    def spread(self) -> Optional[float]:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return round(ba - bb, 6)

    def mid_price(self) -> Optional[float]:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    # ------------------------------------------------------------------
    # Depth snapshot — useful for the API and visualizer
    # ------------------------------------------------------------------

    def depth_snapshot(self, levels: int = 5) -> Dict:
        """
        Returns top N bid and ask levels as a dict.
        Format: {"bids": [(price, qty), ...], "asks": [(price, qty), ...]}
        Bids are sorted high->low, asks low->high.
        """
        bids_out: List[Tuple[float, int]] = []
        asks_out: List[Tuple[float, int]] = []

        # iterate bids from highest to lowest
        for price in reversed(self._bids):
            lvl = self._bids[price]
            if not lvl.is_empty():
                bids_out.append((price, lvl.total_qty))
            if len(bids_out) >= levels:
                break

        # iterate asks from lowest to highest
        for price in self._asks:
            lvl = self._asks[price]
            if not lvl.is_empty():
                asks_out.append((price, lvl.total_qty))
            if len(asks_out) >= levels:
                break

        return {
            "symbol": self.symbol,
            "bids": bids_out,
            "asks": asks_out,
            "spread": self.spread(),
            "mid_price": self.mid_price(),
        }

    # ------------------------------------------------------------------
    # Internal helpers used by the matching engine
    # ------------------------------------------------------------------

    def get_best_bid_level(self) -> Optional[PriceLevel]:
        if not self._bids:
            return None
        return self._bids[self._bids.keys()[-1]]

    def get_best_ask_level(self) -> Optional[PriceLevel]:
        if not self._asks:
            return None
        return self._asks[self._asks.keys()[0]]

    def remove_price_level(self, side: OrderSide, price: float):
        book_side = self._bids if side == OrderSide.BID else self._asks
        if price in book_side:
            del book_side[price]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def total_orders_added(self) -> int:
        return self._order_count

    @property
    def open_bid_levels(self) -> int:
        return len(self._bids)

    @property
    def open_ask_levels(self) -> int:
        return len(self._asks)

    def __repr__(self):
        return (
            f"OrderBook({self.symbol} | "
            f"bid={self.best_bid()} ask={self.best_ask()} "
            f"spread={self.spread()} | "
            f"{self.open_bid_levels} bid lvls, {self.open_ask_levels} ask lvls)"
        )
