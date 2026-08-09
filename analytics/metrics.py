"""
analytics/metrics.py

Tracks latency, throughput, and market metrics over time.

Uses a circular buffer (deque with maxlen) for the rolling latency window
so we don't accumulate unbounded memory in long-running simulations.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Dict, List, Optional

from config import LATENCY_WINDOW_SIZE
from core.trade import Trade


class LatencyTracker:
    """
    Rolling latency tracker. Keeps the last N measurements and
    computes percentiles on demand.

    Percentile calculation is just sorted list indexing — not the most
    efficient but fine for window sizes up to ~100k.
    """

    def __init__(self, window_size: int = LATENCY_WINDOW_SIZE):
        self._samples: deque[int] = deque(maxlen=window_size)

    def record(self, latency_ns: int):
        self._samples.append(latency_ns)

    def percentile(self, p: float) -> Optional[float]:
        """p should be 0-100. Returns None if no samples."""
        if not self._samples:
            return None
        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * p / 100)
        idx = min(idx, len(sorted_samples) - 1)
        return sorted_samples[idx]

    def p50(self) -> Optional[float]:
        return self.percentile(50)

    def p95(self) -> Optional[float]:
        return self.percentile(95)

    def p99(self) -> Optional[float]:
        return self.percentile(99)

    def avg(self) -> Optional[float]:
        if not self._samples:
            return None
        return sum(self._samples) / len(self._samples)

    def summary(self) -> Dict:
        return {
            "samples": len(self._samples),
            "avg_ns": round(self.avg() or 0, 1),
            "p50_ns": self.p50(),
            "p95_ns": self.p95(),
            "p99_ns": self.p99(),
        }


class MarketMetrics:
    """
    Tracks market-level metrics over time.
    Records mid-price, spread, and trade volume at each snapshot interval.

    The history lists can be used directly for plotting.
    """

    def __init__(self):
        self.mid_price_history: List[float] = []
        self.spread_history: List[float] = []
        self.trade_count_history: List[int] = []
        self.vwap_history: List[float] = []
        self.timestamps: List[float] = []   # wall clock seconds

        self._total_volume = 0
        self._total_notional = 0.0

    def snapshot(self, mid: Optional[float], spread: Optional[float], trade_count: int):
        """Call this periodically (e.g. every 100 orders) to record state."""
        t = time.time()
        self.timestamps.append(t)
        self.mid_price_history.append(mid or 0.0)
        self.spread_history.append(spread or 0.0)
        self.trade_count_history.append(trade_count)
        self.vwap_history.append(self.vwap())

    def record_trade(self, trade: Trade):
        self._total_volume += trade.quantity
        self._total_notional += trade.value()

    def vwap(self) -> float:
        """Volume-weighted average price."""
        if self._total_volume == 0:
            return 0.0
        return self._total_notional / self._total_volume

    def summary(self) -> Dict:
        return {
            "total_volume": self._total_volume,
            "total_notional": round(self._total_notional, 2),
            "vwap": round(self.vwap(), 4),
            "snapshots_recorded": len(self.timestamps),
        }
