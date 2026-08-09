"""
analytics/visualizer.py

Two visualizations:
  1. Real-time order book depth chart (updates live as orders come in)
  2. Post-run summary plots (mid price over time, spread, trade volume)

Requires matplotlib. If you're running this headless (e.g. in a Docker container),
set MPLBACKEND=Agg in your environment and use save_summary() instead of show().
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
import numpy as np

if TYPE_CHECKING:
    from analytics.metrics import MarketMetrics
    from core.order_book import OrderBook


def plot_depth_chart(book: "OrderBook", ax: plt.Axes = None, title: str = None):
    """
    Renders a market depth chart (the classic 'mountain' chart).
    Shows cumulative bid and ask volume at each price level.

    If ax is provided, draws into that Axes. Otherwise creates a new figure.
    """
    snap = book.depth_snapshot(levels=20)
    bids: List[Tuple[float, int]] = snap["bids"]   # [(price, qty), ...] high->low
    asks: List[Tuple[float, int]] = snap["asks"]   # [(price, qty), ...] low->high

    if not bids and not asks:
        return   # nothing to show

    # cumulative volumes
    bid_prices = [p for p, _ in bids]
    bid_vols = np.cumsum([q for _, q in bids])

    ask_prices = [p for p, _ in asks]
    ask_vols = np.cumsum([q for _, q in asks])

    standalone = ax is None
    if standalone:
        fig, ax = plt.subplots(figsize=(10, 5))

    ax.fill_between(bid_prices, bid_vols, alpha=0.4, color="#2ecc71", step="post", label="Bids")
    ax.fill_between(ask_prices, ask_vols, alpha=0.4, color="#e74c3c", step="post", label="Asks")

    ax.step(bid_prices, bid_vols, color="#27ae60", where="post")
    ax.step(ask_prices, ask_vols, color="#c0392b", where="post")

    mid = snap.get("mid_price")
    if mid:
        ax.axvline(mid, color="white", linestyle="--", linewidth=0.8, alpha=0.6, label=f"Mid: {mid:.2f}")

    ax.set_facecolor("#1a1a2e")
    ax.tick_params(colors="white")
    ax.yaxis.label.set_color("white")
    ax.xaxis.label.set_color("white")
    ax.set_xlabel("Price")
    ax.set_ylabel("Cumulative Volume")
    ax.set_title(title or f"Order Book Depth — {book.symbol}", color="white", pad=10)
    ax.legend(facecolor="#16213e", labelcolor="white", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    if standalone:
        fig.patch.set_facecolor("#0f0f23")
        plt.tight_layout()
        plt.show()


def plot_summary(metrics: "MarketMetrics", symbol: str = ""):
    """
    Post-run summary: 3 subplots.
      - Mid price over time
      - Spread over time
      - Cumulative trade count

    Good for dropping into a README as a screenshot.
    """
    if not metrics.timestamps:
        print("no data to plot yet")
        return

    # relative time in seconds from start
    t0 = metrics.timestamps[0]
    times = [t - t0 for t in metrics.timestamps]

    fig = plt.figure(figsize=(12, 8), facecolor="#0f0f23")
    gs = gridspec.GridSpec(3, 1, hspace=0.45)

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    style = {"color": "#0f0f23", "facecolor": "#1a1a2e"}

    for ax in (ax1, ax2, ax3):
        ax.set_facecolor("#1a1a2e")
        ax.tick_params(colors="#aaa")
        ax.spines["bottom"].set_color("#333")
        ax.spines["left"].set_color("#333")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # mid price
    ax1.plot(times, metrics.mid_price_history, color="#3498db", linewidth=1.2)
    ax1.fill_between(times, metrics.mid_price_history, alpha=0.1, color="#3498db")
    ax1.set_title(f"Mid Price — {symbol}", color="white", fontsize=10)
    ax1.set_ylabel("Price", color="#aaa", fontsize=8)

    # spread
    ax2.plot(times, metrics.spread_history, color="#f39c12", linewidth=1.0)
    ax2.fill_between(times, metrics.spread_history, alpha=0.15, color="#f39c12")
    ax2.set_title("Bid-Ask Spread", color="white", fontsize=10)
    ax2.set_ylabel("Spread", color="#aaa", fontsize=8)

    # trade count
    ax3.bar(times, metrics.trade_count_history, color="#9b59b6", alpha=0.7, width=max(times) / len(times) if times else 1)
    ax3.set_title("Trade Count per Interval", color="white", fontsize=10)
    ax3.set_ylabel("Trades", color="#aaa", fontsize=8)
    ax3.set_xlabel("Time (seconds)", color="#aaa", fontsize=8)

    fig.suptitle("Order Book Simulator — Run Summary", color="white", fontsize=13, y=0.98)
    plt.tight_layout()
    plt.show()


def save_summary(metrics: "MarketMetrics", path: str, symbol: str = ""):
    """Same as plot_summary but saves to file instead of showing. Good for CI/headless."""
    import matplotlib
    matplotlib.use("Agg")
    plot_summary(metrics, symbol=symbol)
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#0f0f23")
    plt.close()
    print(f"saved summary plot to {path}")
