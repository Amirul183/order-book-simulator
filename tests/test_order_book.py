"""
tests/test_order_book.py

Testing the order book's state management: adds, cancels, best price tracking.
Not testing matching here — that's in test_matching_engine.py.
"""

import pytest
from core.order import Order, OrderSide, OrderType
from core.order_book import OrderBook


def limit(side, price, qty, symbol="TEST"):
    return Order(side=side, order_type=OrderType.LIMIT, quantity=qty, price=price, symbol=symbol)


@pytest.fixture
def empty_book():
    return OrderBook(symbol="TEST")


def test_empty_book_has_no_best_prices(empty_book):
    assert empty_book.best_bid() is None
    assert empty_book.best_ask() is None
    assert empty_book.spread() is None
    assert empty_book.mid_price() is None


def test_add_bid(empty_book):
    o = limit(OrderSide.BID, 99.0, 10)
    empty_book.add_limit_order(o)
    assert empty_book.best_bid() == 99.0
    assert empty_book.open_bid_levels == 1


def test_add_ask(empty_book):
    o = limit(OrderSide.ASK, 101.0, 5)
    empty_book.add_limit_order(o)
    assert empty_book.best_ask() == 101.0


def test_best_bid_is_highest(empty_book):
    for p in [98.0, 99.0, 97.0, 99.5]:
        empty_book.add_limit_order(limit(OrderSide.BID, p, 10))
    assert empty_book.best_bid() == 99.5


def test_best_ask_is_lowest(empty_book):
    for p in [102.0, 101.0, 103.0, 100.5]:
        empty_book.add_limit_order(limit(OrderSide.ASK, p, 10))
    assert empty_book.best_ask() == 100.5


def test_spread_calculation(empty_book):
    empty_book.add_limit_order(limit(OrderSide.BID, 99.0, 10))
    empty_book.add_limit_order(limit(OrderSide.ASK, 101.0, 10))
    assert abs(empty_book.spread() - 2.0) < 1e-9


def test_cancel_order(empty_book):
    o = limit(OrderSide.BID, 99.0, 10)
    empty_book.add_limit_order(o)
    result = empty_book.cancel_order(o.order_id)
    assert result is not None
    assert empty_book.best_bid() is None   # level should be cleaned up
    assert empty_book.open_bid_levels == 0


def test_cancel_nonexistent_order(empty_book):
    result = empty_book.cancel_order("nonexistent-id")
    assert result is None


def test_depth_snapshot_structure(empty_book):
    for p in [99.0, 98.0, 97.0]:
        empty_book.add_limit_order(limit(OrderSide.BID, p, 10))
    for p in [101.0, 102.0]:
        empty_book.add_limit_order(limit(OrderSide.ASK, p, 5))

    snap = empty_book.depth_snapshot(levels=5)
    assert "bids" in snap and "asks" in snap
    assert len(snap["bids"]) == 3
    assert len(snap["asks"]) == 2
    # bids should be sorted highest first
    prices = [p for p, _ in snap["bids"]]
    assert prices == sorted(prices, reverse=True)


def test_multiple_orders_same_price(empty_book):
    """FIFO — orders at the same price should be in insertion order."""
    o1 = limit(OrderSide.BID, 100.0, 10)
    o2 = limit(OrderSide.BID, 100.0, 20)
    empty_book.add_limit_order(o1)
    empty_book.add_limit_order(o2)

    lvl = empty_book.get_best_bid_level()
    assert lvl.total_qty == 30
    assert lvl.peek().order_id == o1.order_id   # o1 was first
