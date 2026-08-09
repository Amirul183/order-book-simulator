"""
feeds/synthetic.py

Generates a stream of synthetic orders that roughly resembles real market activity.
Uses a random walk for the mid price so the book doesn't just drift off to infinity.

Not trying to model market microstructure perfectly here — the goal is to have
something realistic-looking for demos and benchmarks.
"""

from __future__ import annotations

import random
from typing import Iterator

from config import (
    SYMBOL,
    TICK_SIZE,
    SYNTHETIC_MID_PRICE,
    SYNTHETIC_SPREAD,
    SYNTHETIC_VOLATILITY,
)
from core.order import Order, OrderSide, OrderType


def _round_to_tick(price: float, tick: float = TICK_SIZE) -> float:
    """Snap a price to the nearest tick. Floating point fun."""
    return round(round(price / tick) * tick, 10)


class SyntheticFeed:
    """
    Generates a stream of random limit and market orders.

    The mid price follows a Gaussian random walk. Bid/ask prices
    are sampled around the mid with a configurable spread.

    Example:
        feed = SyntheticFeed(seed=42)
        for order in feed.stream(n=1000):
            engine.process(order)
    """

    def __init__(
        self,
        symbol: str = SYMBOL,
        mid_price: float = SYNTHETIC_MID_PRICE,
        spread: float = SYNTHETIC_SPREAD,
        volatility: float = SYNTHETIC_VOLATILITY,
        market_order_prob: float = 0.15,   # ~15% of orders are market orders
        seed: int = None,
    ):
        self.symbol = symbol
        self.mid = mid_price
        self.spread = spread
        self.vol = volatility
        self.market_order_prob = market_order_prob

        self._rng = random.Random(seed)

    def _next_mid(self):
        """Gaussian random walk step."""
        self.mid += self._rng.gauss(0, self.vol)
        self.mid = max(self.mid, TICK_SIZE)   # price can't go negative, obviously
        return self.mid

    def _make_limit_order(self) -> Order:
        mid = self._next_mid()
        half_spread = self.spread / 2.0

        side = self._rng.choice([OrderSide.BID, OrderSide.ASK])
        qty = self._rng.randint(1, 100)

        if side == OrderSide.BID:
            # bids cluster below mid
            offset = self._rng.uniform(0, half_spread * 3)
            price = _round_to_tick(mid - half_spread - offset)
        else:
            # asks cluster above mid
            offset = self._rng.uniform(0, half_spread * 3)
            price = _round_to_tick(mid + half_spread + offset)

        price = max(price, TICK_SIZE)

        return Order(
            side=side,
            order_type=OrderType.LIMIT,
            quantity=qty,
            symbol=self.symbol,
            price=price,
        )

    def _make_market_order(self) -> Order:
        self._next_mid()
        side = self._rng.choice([OrderSide.BID, OrderSide.ASK])
        qty = self._rng.randint(1, 50)   # market orders tend to be smaller

        return Order(
            side=side,
            order_type=OrderType.MARKET,
            quantity=qty,
            symbol=self.symbol,
            price=None,
        )

    def next_order(self) -> Order:
        """Generate a single order."""
        if self._rng.random() < self.market_order_prob:
            return self._make_market_order()
        return self._make_limit_order()

    def stream(self, n: int = None) -> Iterator[Order]:
        """
        Yields orders indefinitely (n=None) or up to n orders.
        Useful for testing and benchmarking.
        """
        count = 0
        while True:
            yield self.next_order()
            count += 1
            if n is not None and count >= n:
                break
