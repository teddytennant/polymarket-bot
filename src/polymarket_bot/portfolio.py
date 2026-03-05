"""Virtual balance, positions, and P&L tracking."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from polymarket_bot.models import Fill, Position, Side


class Portfolio:
    def __init__(self, initial_balance: Decimal = Decimal("10000.00")):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.realized_pnl = Decimal("0.00")
        self._positions: dict[tuple[str, Side], _MutablePosition] = {}

    @property
    def positions(self) -> dict[tuple[str, Side], Position]:
        return {
            k: Position(token_id=k[0], side=k[1], quantity=v.quantity, avg_price=v.avg_price)
            for k, v in self._positions.items()
        }

    def record_fill(self, fill: Fill) -> None:
        key = (fill.token_id, fill.side)
        self.balance -= fill.total_cost

        if key in self._positions:
            pos = self._positions[key]
            total_cost = pos.avg_price * pos.quantity + fill.total_cost
            pos.quantity += fill.quantity
            pos.avg_price = total_cost / pos.quantity
        else:
            self._positions[key] = _MutablePosition(
                quantity=fill.quantity,
                avg_price=fill.price,
            )

    def get_position(self, token_id: str, side: Side) -> Optional[Position]:
        key = (token_id, side)
        pos = self._positions.get(key)
        if pos is None:
            return None
        return Position(token_id=token_id, side=side, quantity=pos.quantity, avg_price=pos.avg_price)

    def close_position(
        self,
        token_id: str,
        side: Side,
        close_price: Decimal,
        quantity: int,
    ) -> None:
        key = (token_id, side)
        pos = self._positions.get(key)
        if pos is None:
            raise ValueError(f"No position for {token_id} {side.value}")
        if quantity > pos.quantity:
            raise ValueError(f"Close quantity {quantity} exceeds position {pos.quantity}")

        pnl = (close_price - pos.avg_price) * quantity
        self.realized_pnl += pnl
        self.balance += close_price * quantity

        pos.quantity -= quantity
        if pos.quantity == 0:
            del self._positions[key]

    def settle_market(self, token_id: str, winning_side: str) -> None:
        for side in (Side.YES, Side.NO):
            key = (token_id, side)
            pos = self._positions.get(key)
            if pos is None:
                continue

            if side.value == winning_side:
                settle_price = Decimal("1.00")
            else:
                settle_price = Decimal("0.00")

            pnl = (settle_price - pos.avg_price) * pos.quantity
            self.realized_pnl += pnl
            self.balance += settle_price * pos.quantity
            del self._positions[key]

    def unrealized_pnl(
        self,
        token_id: str,
        side: Side,
        current_price: Decimal,
    ) -> Decimal:
        key = (token_id, side)
        pos = self._positions.get(key)
        if pos is None:
            return Decimal("0.00")
        return (current_price - pos.avg_price) * pos.quantity

    def to_dict(self) -> dict:
        positions = []
        for (token_id, side), pos in self._positions.items():
            positions.append({
                "token_id": token_id,
                "side": side.value,
                "quantity": pos.quantity,
                "avg_price": str(pos.avg_price),
            })
        return {
            "balance": str(self.balance),
            "initial_balance": str(self.initial_balance),
            "realized_pnl": str(self.realized_pnl),
            "positions": positions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Portfolio:
        p = cls(initial_balance=Decimal(data["initial_balance"]))
        p.balance = Decimal(data["balance"])
        p.realized_pnl = Decimal(data["realized_pnl"])
        for pos_data in data.get("positions", []):
            key = (pos_data["token_id"], Side(pos_data["side"]))
            p._positions[key] = _MutablePosition(
                quantity=pos_data["quantity"],
                avg_price=Decimal(pos_data["avg_price"]),
            )
        return p


class _MutablePosition:
    __slots__ = ("quantity", "avg_price")

    def __init__(self, quantity: int, avg_price: Decimal):
        self.quantity = quantity
        self.avg_price = avg_price
