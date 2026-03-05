"""Strategy ABC and MeanReversionStrategy implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from polymarket_bot.models import Market, Orderbook, OrderType, PricePoint, Side
from polymarket_bot.portfolio import Portfolio


@dataclass(frozen=True)
class TradeSignal:
    token_id: str
    side: Side
    order_type: OrderType
    price: Optional[Decimal]
    quantity: int


class Strategy(ABC):
    @abstractmethod
    def evaluate(
        self,
        market: Market,
        yes_orderbook: Orderbook,
        no_orderbook: Orderbook,
        price_history: list[PricePoint],
        portfolio: Portfolio,
    ) -> Optional[TradeSignal]:
        ...

    @abstractmethod
    def select_markets(self, markets: list[Market]) -> list[Market]:
        ...


class MeanReversionStrategy(Strategy):
    def __init__(
        self,
        window: int = 10,
        threshold: Decimal = Decimal("0.05"),
        order_quantity: int = 10,
        min_volume: int = 0,
    ):
        self.window = window
        self.threshold = threshold
        self.order_quantity = order_quantity
        self.min_volume = min_volume

    def evaluate(
        self,
        market: Market,
        yes_orderbook: Orderbook,
        no_orderbook: Orderbook,
        price_history: list[PricePoint],
        portfolio: Portfolio,
    ) -> Optional[TradeSignal]:
        if len(price_history) < self.window:
            return None

        recent = price_history[: self.window]
        mean_price = sum(p.price for p in recent) / len(recent)

        yes_ask = yes_orderbook.best_ask
        no_ask = no_orderbook.best_ask

        # Buy YES if current ask is significantly below the mean
        if yes_ask and yes_ask > Decimal("0") and yes_ask < mean_price - self.threshold:
            return TradeSignal(
                token_id=market.yes_token_id,
                side=Side.YES,
                order_type=OrderType.LIMIT,
                price=yes_ask,
                quantity=self.order_quantity,
            )

        # Buy NO if YES price is significantly above the mean (i.e. NO is cheap)
        if no_ask and no_ask > Decimal("0") and market.yes_price > mean_price + self.threshold:
            return TradeSignal(
                token_id=market.no_token_id,
                side=Side.NO,
                order_type=OrderType.LIMIT,
                price=no_ask,
                quantity=self.order_quantity,
            )

        return None

    def select_markets(self, markets: list[Market]) -> list[Market]:
        return [
            m
            for m in markets
            if m.active
            and not m.closed
            and m.volume >= self.min_volume
            and len(m.token_ids) >= 2
        ]
