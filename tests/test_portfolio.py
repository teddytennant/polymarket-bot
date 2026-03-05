"""Tests for portfolio tracking."""

from decimal import Decimal

import pytest

from polymarket_bot.models import Fill, Side, Position
from polymarket_bot.portfolio import Portfolio


class TestPortfolioInit:
    def test_default_balance(self):
        p = Portfolio()
        assert p.balance == Decimal("10000.00")

    def test_custom_balance(self):
        p = Portfolio(initial_balance=Decimal("5000.00"))
        assert p.balance == Decimal("5000.00")

    def test_empty_positions(self):
        p = Portfolio()
        assert p.positions == {}

    def test_zero_realized_pnl(self):
        p = Portfolio()
        assert p.realized_pnl == Decimal("0.00")


class TestRecordFill:
    def test_buy_deducts_balance(self):
        p = Portfolio()
        fill = Fill(token_id="t", side=Side.YES, price=Decimal("0.65"), quantity=10)
        p.record_fill(fill)
        assert p.balance == Decimal("10000.00") - Decimal("6.50")

    def test_buy_creates_position(self):
        p = Portfolio()
        fill = Fill(token_id="t", side=Side.YES, price=Decimal("0.65"), quantity=10)
        p.record_fill(fill)
        pos = p.get_position("t", Side.YES)
        assert pos is not None
        assert pos.quantity == 10
        assert pos.avg_price == Decimal("0.65")

    def test_multiple_fills_update_avg_price(self):
        p = Portfolio()
        fill1 = Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10)
        fill2 = Fill(token_id="t", side=Side.YES, price=Decimal("0.70"), quantity=10)
        p.record_fill(fill1)
        p.record_fill(fill2)
        pos = p.get_position("t", Side.YES)
        assert pos.quantity == 20
        assert pos.avg_price == Decimal("0.65")

    def test_yes_and_no_positions_separate(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.65"), quantity=10))
        p.record_fill(Fill(token_id="t", side=Side.NO, price=Decimal("0.35"), quantity=5))
        yes_pos = p.get_position("t", Side.YES)
        no_pos = p.get_position("t", Side.NO)
        assert yes_pos.quantity == 10
        assert no_pos.quantity == 5


class TestGetPosition:
    def test_returns_none_for_no_position(self):
        p = Portfolio()
        assert p.get_position("t", Side.YES) is None

    def test_returns_position(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.50"), quantity=1))
        pos = p.get_position("t", Side.YES)
        assert pos is not None


class TestClosePosition:
    def test_close_credits_balance(self):
        p = Portfolio(initial_balance=Decimal("10000.00"))
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        initial = p.balance
        p.close_position("t", Side.YES, close_price=Decimal("0.70"), quantity=10)
        assert p.balance == initial + Decimal("7.00")

    def test_close_records_pnl(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        p.close_position("t", Side.YES, close_price=Decimal("0.70"), quantity=10)
        assert p.realized_pnl == Decimal("1.00")

    def test_partial_close(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        p.close_position("t", Side.YES, close_price=Decimal("0.70"), quantity=5)
        pos = p.get_position("t", Side.YES)
        assert pos.quantity == 5
        assert p.realized_pnl == Decimal("0.50")

    def test_close_removes_empty_position(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        p.close_position("t", Side.YES, close_price=Decimal("0.70"), quantity=10)
        assert p.get_position("t", Side.YES) is None

    def test_close_nonexistent_raises(self):
        p = Portfolio()
        with pytest.raises(ValueError, match="No position"):
            p.close_position("t", Side.YES, close_price=Decimal("0.70"), quantity=1)

    def test_close_too_many_raises(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=5))
        with pytest.raises(ValueError, match="exceeds"):
            p.close_position("t", Side.YES, close_price=Decimal("0.70"), quantity=10)


class TestSettleMarket:
    def test_settle_yes_winner(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        balance_before = p.balance
        p.settle_market("t", winning_side="yes")
        assert p.balance == balance_before + Decimal("10.00")
        assert p.get_position("t", Side.YES) is None

    def test_settle_no_winner(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.NO, price=Decimal("0.35"), quantity=10))
        balance_before = p.balance
        p.settle_market("t", winning_side="no")
        assert p.balance == balance_before + Decimal("10.00")
        assert p.get_position("t", Side.NO) is None

    def test_settle_losing_yes(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        balance_before = p.balance
        p.settle_market("t", winning_side="no")
        assert p.balance == balance_before
        assert p.get_position("t", Side.YES) is None

    def test_settle_records_pnl(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        p.settle_market("t", winning_side="yes")
        assert p.realized_pnl == Decimal("4.00")

    def test_settle_both_sides(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        p.record_fill(Fill(token_id="t", side=Side.NO, price=Decimal("0.35"), quantity=5))
        p.settle_market("t", winning_side="yes")
        assert p.realized_pnl == Decimal("2.25")


class TestUnrealizedPnl:
    def test_unrealized_pnl_at_current_price(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        pnl = p.unrealized_pnl("t", Side.YES, current_price=Decimal("0.70"))
        assert pnl == Decimal("1.00")

    def test_unrealized_loss(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        pnl = p.unrealized_pnl("t", Side.YES, current_price=Decimal("0.50"))
        assert pnl == Decimal("-1.00")

    def test_unrealized_no_position(self):
        p = Portfolio()
        pnl = p.unrealized_pnl("t", Side.YES, current_price=Decimal("0.70"))
        assert pnl == Decimal("0.00")


class TestSerialization:
    def test_to_dict(self):
        p = Portfolio(initial_balance=Decimal("10000.00"))
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        d = p.to_dict()
        assert d["balance"] == "9994.00"
        assert d["initial_balance"] == "10000.00"
        assert d["realized_pnl"] == "0.00"
        assert len(d["positions"]) == 1

    def test_from_dict(self):
        d = {
            "balance": "9994.00",
            "initial_balance": "10000.00",
            "realized_pnl": "0.00",
            "positions": [
                {
                    "token_id": "t",
                    "side": "yes",
                    "quantity": 10,
                    "avg_price": "0.60",
                }
            ],
        }
        p = Portfolio.from_dict(d)
        assert p.balance == Decimal("9994.00")
        assert p.initial_balance == Decimal("10000.00")
        pos = p.get_position("t", Side.YES)
        assert pos is not None
        assert pos.quantity == 10

    def test_roundtrip(self):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10))
        p.record_fill(Fill(token_id="x", side=Side.NO, price=Decimal("0.40"), quantity=5))
        d = p.to_dict()
        p2 = Portfolio.from_dict(d)
        assert p2.balance == p.balance
        assert p2.get_position("t", Side.YES).quantity == 10
        assert p2.get_position("x", Side.NO).quantity == 5
