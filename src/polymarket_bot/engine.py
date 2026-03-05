"""Paper trading engine: match orders against real CLOB orderbook levels."""

from __future__ import annotations

from decimal import Decimal

from polymarket_bot.client import PolymarketClient
from polymarket_bot.models import Fill, Order, OrderType, OrderbookLevel, Side
from polymarket_bot.portfolio import Portfolio


class PaperTradingEngine:
    def __init__(self, portfolio: Portfolio, client: PolymarketClient):
        self.portfolio = portfolio
        self.client = client

    def submit_order(self, order: Order) -> list[Fill]:
        if order.order_type == OrderType.LIMIT and order.price is not None:
            if order.price <= Decimal("0.00") or order.price > Decimal("1.00"):
                raise ValueError("Price must be between 0.01 and 1.00")

        orderbook = self.client.get_orderbook(order.token_id)

        # Buying means lifting the ask side of this token's orderbook
        ask_levels = sorted(orderbook.asks, key=lambda l: l.price)
        fills = self._match(order, ask_levels)

        if fills:
            total_cost = sum(f.total_cost for f in fills)
            if total_cost > self.portfolio.balance:
                raise ValueError(
                    f"Insufficient balance: need {total_cost}, have {self.portfolio.balance}"
                )

        for fill in fills:
            self.portfolio.record_fill(fill)

        return fills

    def _match(self, order: Order, ask_levels: list[OrderbookLevel]) -> list[Fill]:
        fills: list[Fill] = []
        remaining = order.quantity

        for level in ask_levels:
            if remaining <= 0:
                break

            if order.order_type == OrderType.LIMIT and order.price is not None:
                if level.price > order.price:
                    break

            fill_qty = min(remaining, level.quantity)
            fills.append(
                Fill(
                    token_id=order.token_id,
                    side=order.side,
                    price=level.price,
                    quantity=fill_qty,
                )
            )
            remaining -= fill_qty

        return fills

    def sell_position(self, token_id: str, side: Side, quantity: int) -> list[Fill]:
        """Sell contracts by matching against bid levels (highest first)."""
        position = self.portfolio.get_position(token_id, side)
        if position is None:
            raise ValueError(f"No position for {token_id} {side.value}")
        if quantity > position.quantity:
            raise ValueError(
                f"Sell quantity {quantity} exceeds position {position.quantity}"
            )

        orderbook = self.client.get_orderbook(token_id)
        bid_levels = sorted(orderbook.bids, key=lambda l: l.price, reverse=True)

        fills: list[Fill] = []
        remaining = quantity

        for level in bid_levels:
            if remaining <= 0:
                break
            fill_qty = min(remaining, level.quantity)
            fills.append(
                Fill(
                    token_id=token_id,
                    side=side,
                    price=level.price,
                    quantity=fill_qty,
                )
            )
            remaining -= fill_qty

        for fill in fills:
            self.portfolio.close_position(
                token_id=fill.token_id,
                side=fill.side,
                close_price=fill.price,
                quantity=fill.quantity,
            )

        return fills

    def check_settlements(self, token_market_map: dict[str, str]) -> None:
        """Check markets for resolution. token_market_map: {token_id: condition_id}."""
        for token_id, condition_id in token_market_map.items():
            market = self.client.get_market(condition_id)
            if not market.closed:
                continue

            # Determine which side won
            if len(market.outcome_prices) >= 2:
                if market.outcome_prices[0] >= Decimal("0.99"):
                    winning_side = "yes"
                elif market.outcome_prices[1] >= Decimal("0.99"):
                    winning_side = "no"
                else:
                    continue
            else:
                continue

            self.portfolio.settle_market(token_id, winning_side=winning_side)
