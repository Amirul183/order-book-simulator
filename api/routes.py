"""
api/routes.py

REST API routes for the order book simulator.
Keeps all the FastAPI plumbing in one place so simulator.py stays clean.

Endpoints:
  POST /order              — submit a new order
  DELETE /order/{id}       — cancel an order
  GET  /orderbook          — full depth snapshot (top N levels)
  GET  /orderbook/l1       — best bid/ask only
  GET  /trades             — recent trade tape
  GET  /stats              — engine stats (latency, throughput, etc.)
  GET  /symbols            — list of active symbols
  GET  /health             — health check

WebSocket:
  WS   /ws/{symbol}        — real-time order book + trade stream (see api/ws.py)
"""

from __future__ import annotations

from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field, field_validator

from core.matching_engine import MatchingEngine
from core.order import Order, OrderSide, OrderType
from feeds.market_data import format_trade_tape, l1_snapshot, l2_snapshot, order_imbalance

router = APIRouter()

# symbol -> engine mapping — populated during app startup
_engines: Dict[str, MatchingEngine] = {}


def register_engine(symbol: str, engine: MatchingEngine) -> None:
    """Called at startup to register each symbol's engine."""
    _engines[symbol.upper()] = engine


def get_engine_for_symbol(symbol: str) -> MatchingEngine:
    """Retrieve a registered engine, or raise if the symbol isn't active."""
    key = symbol.upper()
    if key not in _engines:
        raise HTTPException(
            status_code=404,
            detail=f"symbol '{key}' not found — active symbols: {list(_engines.keys())}",
        )
    return _engines[key]


def get_engine() -> MatchingEngine:
    """Returns the first registered engine (default symbol). Used by legacy routes."""
    if not _engines:
        raise RuntimeError("no engines registered — call register_engine() at startup")
    return next(iter(_engines.values()))


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------

class OrderRequest(BaseModel):
    side: str = Field(..., description="'bid' or 'ask'")
    order_type: str = Field("limit", description="'limit' or 'market'")
    quantity: int = Field(..., gt=0, description="order size (must be > 0)")
    price: Optional[float] = Field(None, description="required for limit orders; omit for market orders")
    symbol: str = Field("AAPL", description="instrument symbol (e.g. AAPL, TSLA)")

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v.lower() not in ("bid", "ask"):
            raise ValueError("side must be 'bid' or 'ask'")
        return v.lower()

    @field_validator("order_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v.lower() not in ("limit", "market"):
            raise ValueError("order_type must be 'limit' or 'market'")
        return v.lower()

    @field_validator("symbol")
    @classmethod
    def normalise_symbol(cls, v: str) -> str:
        return v.upper()


class ModifyRequest(BaseModel):
    quantity: Optional[int] = Field(None, gt=0, description="new order size (must be > 0)")
    price: Optional[float] = Field(None, description="new price for the order")
    symbol: str = Field("AAPL", description="instrument symbol")

    @field_validator("symbol")
    @classmethod
    def normalise_symbol(cls, v: str) -> str:
        return v.upper()


class OrderResponse(BaseModel):
    order_id: str
    status: str
    trades_executed: int
    message: str


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@router.get("/health")
def health():
    return {
        "status": "ok",
        "active_symbols": list(_engines.keys()),
        "total_engines": len(_engines),
    }


@router.get("/symbols")
def list_symbols() -> List[str]:
    """Returns the list of symbols with active engines."""
    return list(_engines.keys())


@router.post("/order", response_model=OrderResponse)
def submit_order(req: OrderRequest) -> OrderResponse:
    engine = get_engine_for_symbol(req.symbol)

    try:
        order = Order(
            side=OrderSide(req.side),
            order_type=OrderType(req.order_type),
            quantity=req.quantity,
            symbol=req.symbol,
            price=req.price,
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    trades = engine.process(order)

    return OrderResponse(
        order_id=order.order_id,
        status=order.status.value,
        trades_executed=len(trades),
        message=f"order processed — {len(trades)} trade(s) executed",
    )


@router.delete("/order/{order_id}")
def cancel_order(order_id: str, symbol: str = "AAPL"):
    engine = get_engine_for_symbol(symbol)
    cancelled = engine.book.cancel_order(order_id)
    if cancelled is None:
        raise HTTPException(
            status_code=404,
            detail=f"order '{order_id}' not found or already filled",
        )
    return {"cancelled": order_id, "status": "cancelled"}


@router.put("/order/{order_id}")
def modify_order(order_id: str, req: ModifyRequest):
    engine = get_engine_for_symbol(req.symbol)
    
    if order_id not in engine.book._order_index:
        raise HTTPException(
            status_code=404,
            detail=f"order '{order_id}' not found or already filled",
        )
        
    trades = engine.modify_order(
        order_id=order_id,
        new_price=req.price,
        new_qty=req.quantity
    )
    
    return {
        "order_id": order_id,
        "status": "modified",
        "trades_executed": len(trades),
        "message": f"order modified — {len(trades)} trade(s) executed from new matching"
    }


@router.get("/orderbook")
def get_orderbook(symbol: str = "AAPL", levels: int = 10):
    engine = get_engine_for_symbol(symbol)
    snap = l2_snapshot(engine.book, levels=levels)
    snap["imbalance"] = round(order_imbalance(engine.book), 4)
    return snap


@router.get("/orderbook/l1")
def get_l1(symbol: str = "AAPL"):
    return l1_snapshot(get_engine_for_symbol(symbol).book)


@router.get("/trades")
def get_trades(symbol: str = "AAPL", last_n: int = 50):
    engine = get_engine_for_symbol(symbol)
    return {
        "symbol": symbol,
        "total_trades": len(engine.trades),
        "tape": format_trade_tape(engine.trades, last_n=last_n),
    }


@router.get("/stats")
def get_stats(symbol: str = "AAPL"):
    return get_engine_for_symbol(symbol).stats()
