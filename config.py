# config.py
# Central configuration file for all application settings.
# Keeps configuration separate from the matching engine to avoid hardcoding numbers.

SYMBOL = "AAPL"          # default instrument
TICK_SIZE = 0.01         # minimum price increment
LOT_SIZE = 1             # minimum order quantity
MAX_DEPTH_LEVELS = 10    # how many levels to show in depth snapshots

# latency tracking
LATENCY_WINDOW_SIZE = 10_000   # rolling window for percentile calculations

# synthetic feed defaults
SYNTHETIC_MID_PRICE = 100.0
SYNTHETIC_SPREAD = 0.05         # typical spread for a liquid stock
SYNTHETIC_VOLATILITY = 0.02     # std dev per order — controls how wild prices move
SYNTHETIC_ORDER_RATE = 1000     # orders per second in benchmark mode

# api
API_HOST = "127.0.0.1"
API_PORT = 8000
