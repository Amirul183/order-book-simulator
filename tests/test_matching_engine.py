"""
tests/test_matching_engine.py

Tests for the actual matching logic. This is the most important test file.
Covers: simple matches, partial fills, market orders, no-match cases,
        multi-level walks, and price-time priority.
"""

import pytest
from core.matching_engine import MatchingEngine
from core.order import Order, OrderSide, OrderStatus, OrderType


def limit(side, price, qty):
    return Order(side=side, order_type=OrderType.LIMIT, quantity=qty, price=price)


def market(side, qty):
    return Order(side=side, order_type=OrderType.MARKET, quantity=qty)


@pytest.fixture
def engine():
    return MatchingEngine(symbol="TEST")


# ------------------------------------------------------------------
# Basic matching
# ------------------------------------------------------------------

def test_no_match_adds_to_book(engine):
    """Limit order with no counterpart should rest in the book."""
    o = limit(OrderSide.BID, 99.0, 10)
    trades = engine.process(o)
    assert trades == []
    assert engine.book.best_bid() == 99.0


def test_simple_limit_match(engine):
    """Sell sitting in book, buy comes in at matching price."""
    ask = limit(OrderSide.ASK, 100.0, 10)
    engine.process(ask)

    bid = limit(OrderSide.BID, 100.0, 10)
    trades = engine.process(bid)

    assert len(trades) == 1
    assert trades[0].price == 100.0
    assert trades[0].quantity == 10
    # both orders fully filled — book should be empty now
    assert engine.book.best_ask() is None
    assert engine.book.best_bid() is None


def test_partial_fill(engine):
    """Ask for 10, bid for 5 — ask partially fills, remaining 5 stays in book."""
    engine.process(limit(OrderSide.ASK, 100.0, 10))
    trades = engine.process(limit(OrderSide.BID, 100.0, 5))

    assert len(trades) == 1
    assert trades[0].quantity == 5
    assert engine.book.best_ask() == 100.0   # still has 5 left

    lvl = engine.book.get_best_ask_level()
    assert lvl.total_qty == 5


def test_aggressor_partial_fill(engine):
    """Bid for 20, only 10 available — bid fills 10, remaining 10 rests as limit."""
    engine.process(limit(OrderSide.ASK, 100.0, 10))
    bid = limit(OrderSide.BID, 100.0, 20)
    trades = engine.process(bid)

    assert len(trades) == 1
    assert trades[0].quantity == 10
    assert engine.book.best_bid() == 100.0   # leftover bid is now in book
    assert engine.book.get_best_bid_level().total_qty == 10


def test_price_priority(engine):
    """Best ask should match first — even if it was added second."""
    engine.process(limit(OrderSide.ASK, 102.0, 10))
    engine.process(limit(OrderSide.ASK, 100.0, 10))   # better price, added later

    bid = limit(OrderSide.BID, 102.0, 10)
    trades = engine.process(bid)

    # should match at 100 (best ask), not 102
    assert trades[0].price == 100.0


def test_time_priority_same_price(engine):
    """Two asks at same price — earlier one should match first (FIFO)."""
    ask1 = limit(OrderSide.ASK, 100.0, 5)
    ask2 = limit(OrderSide.ASK, 100.0, 5)
    engine.process(ask1)
    engine.process(ask2)

    bid = limit(OrderSide.BID, 100.0, 5)
    trades = engine.process(bid)

    assert len(trades) == 1
    assert trades[0].seller_order_id == ask1.order_id   # ask1 was first


def test_multi_level_fill(engine):
    """Bid large enough to sweep through multiple ask price levels."""
    engine.process(limit(OrderSide.ASK, 100.0, 10))
    engine.process(limit(OrderSide.ASK, 101.0, 10))
    engine.process(limit(OrderSide.ASK, 102.0, 10))

    bid = limit(OrderSide.BID, 102.0, 25)
    trades = engine.process(bid)

    # fills 10@100, 10@101, 5@102
    assert len(trades) == 3
    total_qty = sum(t.quantity for t in trades)
    assert total_qty == 25


def test_market_order_fills_against_book(engine):
    engine.process(limit(OrderSide.ASK, 99.0, 20))

    mkt = market(OrderSide.BID, 10)
    trades = engine.process(mkt)

    assert len(trades) == 1
    assert trades[0].quantity == 10
    assert trades[0].price == 99.0   # takes the resting price


def test_market_order_empty_book(engine):
    """Market order with nothing to match against — should generate no trades."""
    mkt = market(OrderSide.BID, 10)
    trades = engine.process(mkt)
    assert trades == []


def test_bid_does_not_match_below_ask(engine):
    """Bid at 99, ask at 101 — no match."""
    engine.process(limit(OrderSide.ASK, 101.0, 10))
    trades = engine.process(limit(OrderSide.BID, 99.0, 10))
    assert trades == []
    assert engine.book.best_bid() == 99.0
    assert engine.book.best_ask() == 101.0


def test_trade_count_accumulates(engine):
    for _ in range(5):
        engine.process(limit(OrderSide.ASK, 100.0, 1))
        engine.process(limit(OrderSide.BID, 100.0, 1))
    assert len(engine.trades) == 5


def test_stats_returns_expected_keys(engine):
    engine.process(limit(OrderSide.ASK, 100.0, 10))
    engine.process(limit(OrderSide.BID, 100.0, 10))
    s = engine.stats()
    for key in ("processed", "trades_executed", "avg_latency_ns", "throughput"):
        assert key in s
