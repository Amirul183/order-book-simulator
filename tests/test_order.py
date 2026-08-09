"""
tests/test_order.py
"""
import pytest
from core.order import Order, OrderSide, OrderStatus, OrderType


def make_limit(side, price, qty):
    return Order(side=side, order_type=OrderType.LIMIT, quantity=qty, price=price)


def test_basic_creation():
    o = make_limit(OrderSide.BID, 100.0, 50)
    assert o.remaining_qty == 50
    assert o.status == OrderStatus.OPEN
    assert o.is_active()


def test_partial_fill():
    o = make_limit(OrderSide.BID, 100.0, 100)
    o.fill(60)
    assert o.remaining_qty == 40
    assert o.status == OrderStatus.PARTIALLY_FILLED
    assert o.is_active()


def test_full_fill():
    o = make_limit(OrderSide.ASK, 99.5, 30)
    o.fill(30)
    assert o.remaining_qty == 0
    assert o.status == OrderStatus.FILLED
    assert not o.is_active()


def test_overfill_raises():
    o = make_limit(OrderSide.BID, 50.0, 10)
    with pytest.raises(ValueError):
        o.fill(11)


def test_limit_order_requires_price():
    with pytest.raises(ValueError):
        Order(side=OrderSide.BID, order_type=OrderType.LIMIT, quantity=10, price=None)


def test_market_order_no_price_ok():
    o = Order(side=OrderSide.BID, order_type=OrderType.MARKET, quantity=5)
    assert o.price is None
    assert o.is_active()


def test_nonpositive_qty_raises():
    with pytest.raises(ValueError):
        Order(side=OrderSide.BID, order_type=OrderType.LIMIT, quantity=0, price=10.0)


def test_order_id_unique():
    ids = {make_limit(OrderSide.BID, 100.0, 1).order_id for _ in range(1000)}
    assert len(ids) == 1000   # all unique
