"""
core/matching_engine.py

The heart of the simulator. Takes incoming orders and figures out if they
can match against resting orders in the book. If yes, executes a trade.
If no, adds the order to the book.

Matching logic: price-time priority (FIFO).
  - A new bid matches if its price >= best ask
  - A new ask matches if its price <= best bid
  - Market orders match at whatever price is available

Events emitted after each order are stored in self.event_log. If you want
to build something reactive on top of this, that's where to hook in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional

from core.order import Order, OrderSide, OrderType
from core.order_book import OrderBook
from core.trade import Trade
from analytics.metrics import LatencyTracker

__all__ = ["MatchingEngine", "Event", "EventType"]




class EventType(Enum):
    ORDER_ADDED = "order_added"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_MODIFIED = "order_modified"
    ORDER_REJECTED = "order_rejected"
    TRADE_EXECUTED = "trade_executed"
    BOOK_UPDATED = "book_updated"


@dataclass
class Event:
    event_type: EventType
    timestamp: int
    order: Optional[Order] = None
    trade: Optional[Trade] = None
    metadata: Optional[dict] = None


class MatchingEngine:
    """
    Wraps the OrderBook and handles the actual matching logic.

    Usage:
        engine = MatchingEngine()
        trades = engine.process(order)
    """

    def __init__(self, symbol: str = "AAPL"):
        self.book = OrderBook(symbol)
        self.symbol = symbol

        self.trades: List[Trade] = []
        self.event_log: List[Event] = []

        # optional callback for when trades happen (e.g., analytics hooks)
        self._on_trade: Optional[Callable[[Trade], None]] = None

        self._processed_count = 0
        self._total_latency_ns = 0
        self._latency_tracker = LatencyTracker()  # rolling window for percentiles

    def on_trade(self, callback: Callable[[Trade], None]):
        """Register a callback that fires on every trade execution."""
        self._on_trade = callback

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process(self, order: Order) -> List[Trade]:
        """
        Process an incoming order. Returns list of trades generated (may be empty).
        This is the hot path — keep it fast.
        """
        start = time.perf_counter_ns()

        if order.order_type == OrderType.CANCEL:
            return self._handle_cancel(order)

        new_trades = []

        if order.order_type == OrderType.MARKET:
            new_trades = self._match_market(order)
        elif order.order_type == OrderType.LIMIT:
            new_trades = self._match_limit(order)

        # if the order still has qty left and it's a limit, it rests in the book
        if order.order_type == OrderType.LIMIT and order.remaining_qty > 0 and order.is_active():
            self.book.add_limit_order(order)
            self._emit(EventType.ORDER_ADDED, order=order)

        self.trades.extend(new_trades)
        self._processed_count += 1
        elapsed_ns = time.perf_counter_ns() - start
        self._total_latency_ns += elapsed_ns
        self._latency_tracker.record(elapsed_ns)

        return new_trades

    # ------------------------------------------------------------------
    # Matching logic
    # ------------------------------------------------------------------

    def _match_limit(self, order: Order) -> List[Trade]:
        trades = []

        if order.side == OrderSide.BID:
            # new buy order — match against asks
            while order.remaining_qty > 0:
                best_ask_lvl = self.book.get_best_ask_level()
                if best_ask_lvl is None:
                    break
                if best_ask_lvl.price > order.price:
                    break   # can't afford it

                trades.extend(self._execute_match(order, best_ask_lvl, OrderSide.ASK))

        else:
            # new sell order — match against bids
            while order.remaining_qty > 0:
                best_bid_lvl = self.book.get_best_bid_level()
                if best_bid_lvl is None:
                    break
                if best_bid_lvl.price < order.price:
                    break   # not willing to sell this cheap

                trades.extend(self._execute_match(order, best_bid_lvl, OrderSide.BID))

        return trades

    def _match_market(self, order: Order) -> List[Trade]:
        """Market orders take whatever is available. No price check."""
        trades = []

        opposite = OrderSide.ASK if order.side == OrderSide.BID else OrderSide.BID

        while order.remaining_qty > 0:
            if opposite == OrderSide.ASK:
                lvl = self.book.get_best_ask_level()
            else:
                lvl = self.book.get_best_bid_level()

            if lvl is None:
                # nothing in the book — market order is unfilled (or partially)
                # real exchanges handle this differently but for now just stop
                break

            trades.extend(self._execute_match(order, lvl, opposite))

        return trades

    def _execute_match(self, aggressor: Order, level, resting_side: OrderSide) -> List[Trade]:
        """
        Walk through orders at a price level, filling against the aggressor.
        Generates Trade objects for each fill.
        """
        trades = []

        while aggressor.remaining_qty > 0 and not level.is_empty():
            resting = level.peek()
            if resting is None:
                break

            fill_qty = min(aggressor.remaining_qty, resting.remaining_qty)
            fill_price = resting.price   # passive order sets the price (standard)

            # determine buyer/seller
            if aggressor.side == OrderSide.BID:
                buyer_id, seller_id = aggressor.order_id, resting.order_id
            else:
                buyer_id, seller_id = resting.order_id, aggressor.order_id

            trade = Trade(
                buyer_order_id=buyer_id,
                seller_order_id=seller_id,
                price=fill_price,
                quantity=fill_qty,
                symbol=self.symbol,
            )
            trades.append(trade)

            # update quantities
            aggressor.fill(fill_qty)
            resting.fill(fill_qty)
            level.update_qty(fill_qty)

            self._emit(EventType.TRADE_EXECUTED, order=aggressor, trade=trade)

            if self._on_trade:
                self._on_trade(trade)

            # if resting order is fully filled, pop it from the level
            if not resting.is_active():
                level.orders.popleft()
                # clean up the index too
                self.book._order_index.pop(resting.order_id, None)

        # if the level is now empty, remove it from the book
        if level.is_empty():
            self.book.remove_price_level(resting_side, level.price)

        return trades

    # ------------------------------------------------------------------
    # Cancellations & Modifications
    # ------------------------------------------------------------------

    def modify_order(self, order_id: str, new_price: Optional[float] = None, new_qty: Optional[int] = None) -> List[Trade]:
        if order_id not in self.book._order_index:
            self._emit(EventType.ORDER_REJECTED, metadata={"reason": f"modify failed: {order_id} not found"})
            return []
            
        side, current_price = self.book._order_index[order_id]
        book_side = self.book._bids if side == OrderSide.BID else self.book._asks
        level = book_side.get(current_price)
        
        if level is None:
            return []
            
        order_to_modify = None
        for o in level.orders:
            if o.order_id == order_id:
                order_to_modify = o
                break
                
        if not order_to_modify:
            return []
            
        # Fast path: purely a quantity reduction (keeps queue priority)
        is_pure_reduction = (
            (new_price is None or new_price == current_price) and 
            (new_qty is not None and new_qty < order_to_modify.remaining_qty)
        )
        
        if is_pure_reduction:
            diff = order_to_modify.remaining_qty - new_qty
            order_to_modify.quantity -= diff
            order_to_modify.remaining_qty = new_qty
            level._recalculate_qty()
            self._emit(EventType.ORDER_MODIFIED, order=order_to_modify)
            return []
            
        # Otherwise, cancel and replace (loses queue priority)
        cancelled = self.book.cancel_order(order_id)
        if not cancelled:
            return []
            
        final_price = new_price if new_price is not None else current_price
        final_qty = new_qty if new_qty is not None else cancelled.remaining_qty
        
        new_order = Order(
            side=cancelled.side,
            order_type=OrderType.LIMIT,
            quantity=final_qty,
            symbol=self.symbol,
            price=final_price
        )
        new_order.order_id = cancelled.order_id  # Preserve original order ID
        
        self._emit(EventType.ORDER_MODIFIED, order=new_order)
        return self.process(new_order)

    def _handle_cancel(self, order: Order) -> List[Trade]:
        """
        Process a cancel request. The order_id on the incoming order is treated
        as the ID of the order to cancel. A dedicated CancelRequest type would be
        cleaner long-term, but this keeps the Order model simple for now.
        """
        cancelled = self.book.cancel_order(order.order_id)
        if cancelled:
            self._emit(EventType.ORDER_CANCELLED, order=cancelled)
        else:
            self._emit(EventType.ORDER_REJECTED, order=order,
                       metadata={"reason": "order not found or already filled"})
        return []

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _emit(self, event_type: EventType, order=None, trade=None, metadata=None):
        self.event_log.append(Event(
            event_type=event_type,
            timestamp=time.perf_counter_ns(),
            order=order,
            trade=trade,
            metadata=metadata,
        ))

    # ------------------------------------------------------------------
    # Stats / diagnostics
    # ------------------------------------------------------------------

    @property
    def avg_latency_ns(self) -> float:
        if self._processed_count == 0:
            return 0.0
        return self._total_latency_ns / self._processed_count

    @property
    def throughput(self) -> str:
        """Rough throughput estimate based on avg latency."""
        if self.avg_latency_ns == 0:
            return "N/A"
        ops_per_sec = 1_000_000_000 / self.avg_latency_ns
        return f"{ops_per_sec:,.0f} orders/sec"

    def stats(self) -> dict:
        lat = self._latency_tracker.summary()
        return {
            "processed": self._processed_count,
            "trades_executed": len(self.trades),
            "avg_latency_ns": round(self.avg_latency_ns, 2),
            "p50_ns": lat["p50_ns"],
            "p95_ns": lat["p95_ns"],
            "p99_ns": lat["p99_ns"],
            "throughput": self.throughput,
            "open_bid_levels": self.book.open_bid_levels,
            "open_ask_levels": self.book.open_ask_levels,
            "best_bid": self.book.best_bid(),
            "best_ask": self.book.best_ask(),
            "spread": self.book.spread(),
        }

    def __repr__(self):
        return f"MatchingEngine({self.symbol} | {self._processed_count} processed | {len(self.trades)} trades)"
