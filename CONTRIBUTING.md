# Contributing to Order Book Simulator

Thanks for taking the time to contribute! This is a learning project, so questions, ideas, and improvements of any kind are welcome.

---

## Getting Started

```bash
# 1. Fork and clone
git clone https://github.com/yourusername/orderbook-simulator.git
cd orderbook-simulator

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install in editable mode with dev dependencies
pip install -e ".[dev]"

# 4. Run the tests
pytest tests/ -v

# 5. Start the server
python simulator.py
```

---

## How to Contribute

### Reporting Bugs

Please open a GitHub Issue with:
- What you did
- What you expected to happen
- What actually happened
- Python version and OS

### Suggesting Features

Open an Issue first to discuss the idea before writing code. That way we avoid duplicate work and can agree on the design upfront.

### Submitting Code

1. Create a feature branch: `git checkout -b feature/my-idea`
2. Write your code and add tests for any new logic
3. Make sure all tests pass: `pytest tests/ -v`
4. Run the linter: `ruff check .`
5. Open a Pull Request with a clear description of what changed and why

---

## Code Style

- **Formatter**: The project uses `ruff` for linting. Run `ruff check .` before pushing.
- **Docstrings**: Write module-level docstrings explaining *what* the module does and *why* key decisions were made — not just *how*.
- **Comments**: Prefer clear variable names over inline comments. When a comment is needed, explain the *why*, not the *what*.
- **Type hints**: Use them for all public functions. `from __future__ import annotations` is already imported in each module.

---

## Project Structure

```
core/          ← matching engine, order book, data models  (no I/O here)
api/           ← FastAPI routes + WebSocket handler
feeds/         ← synthetic data generator, market data formatting
analytics/     ← latency tracking, market metrics, visualizations
tests/         ← pytest unit tests
benchmarks/    ← standalone throughput benchmark
static/        ← dashboard HTML/CSS/JS
```

---

## Ideas for Extensions

Here are some directions the project could grow in — feel free to pick one up:

- **Iceberg orders** — show a partial visible quantity, hide the rest
- **Stop-loss / stop-limit orders** — triggered when price crosses a threshold
- **LOBSTER dataset replay** — replay real market data instead of synthetic feed
- **Persistent state** — write the trade log to SQLite or a CSV
- **Order book heatmap** — visualize order density as a heatmap over time
- **Replace Python with Cython** — 5–10x speedup on the matching hot path

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
