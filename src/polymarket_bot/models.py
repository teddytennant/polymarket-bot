"""Frozen dataclasses for all domain models."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional


class Side(Enum):
    YES = "yes"
    NO = "no"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class OrderbookLevel:
    price: Decimal
    quantity: int


@dataclass(frozen=True)
class Market:
    """A single Polymarket binary market (one question, Yes/No outcomes)."""
    condition_id: str
    question: str
    slug: str
    status: str
    outcomes: tuple[str, ...]
    outcome_prices: tuple[Decimal, ...]
    token_ids: tuple[str, ...]
    volume: Decimal
    liquidity: Decimal
    active: bool
    closed: bool
    end_date: str
    description: str

    @property
    def yes_price(self) -> Decimal:
        if len(self.outcome_prices) >= 1:
            return self.outcome_prices[0]
        return Decimal("0")

    @property
    def no_price(self) -> Decimal:
        if len(self.outcome_prices) >= 2:
            return self.outcome_prices[1]
        return Decimal("0")

    @property
    def yes_token_id(self) -> str:
        if len(self.token_ids) >= 1:
            return self.token_ids[0]
        return ""

    @property
    def no_token_id(self) -> str:
        if len(self.token_ids) >= 2:
            return self.token_ids[1]
        return ""

    @classmethod
    def from_api(cls, data: dict) -> Market:
        outcomes = tuple(data.get("outcomes", ["Yes", "No"]))

        raw_prices = data.get("outcomePrices", [])
        if isinstance(raw_prices, str):
            import json
            raw_prices = json.loads(raw_prices)
        outcome_prices = tuple(Decimal(str(p)) for p in raw_prices)

        raw_tokens = data.get("clobTokenIds", [])
        if isinstance(raw_tokens, str):
            import json
            raw_tokens = json.loads(raw_tokens)
        token_ids = tuple(str(t) for t in raw_tokens)

        return cls(
            condition_id=data.get("conditionId", data.get("condition_id", "")),
            question=data.get("question", ""),
            slug=data.get("slug", ""),
            status=_resolve_status(data),
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            token_ids=token_ids,
            volume=Decimal(str(data.get("volume", 0))),
            liquidity=Decimal(str(data.get("liquidity", 0))),
            active=bool(data.get("active", False)),
            closed=bool(data.get("closed", False)),
            end_date=data.get("endDate", data.get("end_date", "")),
            description=data.get("description", ""),
        )


def _resolve_status(data: dict) -> str:
    if data.get("closed"):
        return "closed"
    if data.get("active"):
        return "active"
    return "inactive"


@dataclass(frozen=True)
class Orderbook:
    """CLOB orderbook snapshot for a single token."""
    token_id: str
    bids: tuple[OrderbookLevel, ...]
    asks: tuple[OrderbookLevel, ...]

    @classmethod
    def from_api(cls, token_id: str, data: dict) -> Orderbook:
        bids = tuple(
            OrderbookLevel(
                price=Decimal(str(level["price"])),
                quantity=int(Decimal(str(level["size"]))),
            )
            for level in data.get("bids", [])
        )
        asks = tuple(
            OrderbookLevel(
                price=Decimal(str(level["price"])),
                quantity=int(Decimal(str(level["size"]))),
            )
            for level in data.get("asks", [])
        )
        return cls(token_id=token_id, bids=bids, asks=asks)

    @property
    def best_bid(self) -> Optional[Decimal]:
        if not self.bids:
            return None
        return max(level.price for level in self.bids)

    @property
    def best_ask(self) -> Optional[Decimal]:
        if not self.asks:
            return None
        return min(level.price for level in self.asks)


@dataclass(frozen=True)
class PricePoint:
    """Historical price data point."""
    timestamp: int
    price: Decimal

    @classmethod
    def from_api(cls, data: dict) -> PricePoint:
        return cls(
            timestamp=int(data["t"]),
            price=Decimal(str(data["p"])),
        )


@dataclass(frozen=True)
class Order:
    token_id: str
    side: Side
    order_type: OrderType
    price: Optional[Decimal]
    quantity: int
    status: OrderStatus


@dataclass(frozen=True)
class Position:
    token_id: str
    side: Side
    quantity: int
    avg_price: Decimal

    @property
    def cost_basis(self) -> Decimal:
        return self.avg_price * self.quantity


@dataclass(frozen=True)
class Fill:
    token_id: str
    side: Side
    price: Decimal
    quantity: int

    @property
    def total_cost(self) -> Decimal:
        return self.price * self.quantity
