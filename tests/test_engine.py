"""Tests for paper trading engine."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from polymarket_bot.models import (
    Fill,
    Market,
    Order,
    Orderbook,
    OrderbookLevel,
    OrderStatus,
    OrderType,
    Side,
)
from polymarket_bot.portfolio import Portfolio
from polymarket_bot.engine import PaperTradingEngine


@pytest.fixture
def portfolio():
    return Portfolio(initial_balance=Decimal("10000.00"))


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def engine(portfolio, mock_client):
    return PaperTradingEngine(portfolio=portfolio, client=mock_client)


@pytest.fixture
def sample_orderbook():
    return Orderbook(
        token_id="yes_token",
        bids=tuple([
            OrderbookLevel(price=Decimal("0.65"), quantity=100),
            OrderbookLevel(price=Decimal("0.63"), quantity=200),
            OrderbookLevel(price=Decimal("0.60"), quantity=150),
        ]),
        asks=tuple([
            OrderbookLevel(price=Decimal("0.67"), quantity=120),
            OrderbookLevel(price=Decimal("0.70"), quantity=80),
            OrderbookLevel(price=Decimal("0.72"), quantity=200),
        ]),
    )


class TestMarketOrder:
    def test_fills_at_best_ask(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            token_id="yes_token",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=10,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 1
        assert fills[0].price == Decimal("0.67")
        assert fills[0].quantity == 10
        assert fills[0].side == Side.YES

    def test_walks_multiple_ask_levels(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            token_id="yes_token",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=150,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 2
        assert fills[0].quantity == 120
        assert fills[0].price == Decimal("0.67")
        assert fills[1].quantity == 30
        assert fills[1].price == Decimal("0.70")


class TestLimitOrder:
    def test_limit_fills_within_price(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            token_id="yes_token",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.67"),
            quantity=200,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 1
        assert fills[0].quantity == 120
        assert fills[0].price == Decimal("0.67")

    def test_limit_no_fill_when_price_too_low(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            token_id="yes_token",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.50"),
            quantity=10,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 0


class TestValidation:
    def test_insufficient_balance(self, engine, mock_client, sample_orderbook):
        engine.portfolio.balance = Decimal("1.00")
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            token_id="yes_token",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=100,
            status=OrderStatus.PENDING,
        )
        with pytest.raises(ValueError, match="Insufficient balance"):
            engine.submit_order(order)

    def test_invalid_limit_price_too_high(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            token_id="yes_token",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("1.01"),
            quantity=10,
            status=OrderStatus.PENDING,
        )
        with pytest.raises(ValueError, match="Price must be between"):
            engine.submit_order(order)

    def test_empty_orderbook(self, engine, mock_client):
        mock_client.get_orderbook.return_value = Orderbook(token_id="t", bids=(), asks=())
        order = Order(
            token_id="t",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=10,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 0


class TestPortfolioIntegration:
    def test_fill_recorded_in_portfolio(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            token_id="yes_token",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=10,
            status=OrderStatus.PENDING,
        )
        engine.submit_order(order)
        pos = engine.portfolio.get_position("yes_token", Side.YES)
        assert pos is not None
        assert pos.quantity == 10


class TestSellPosition:
    def test_sell_matches_bids(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(token_id="t", side=Side.YES, price=Decimal("0.60"), quantity=10)
        )
        mock_client.get_orderbook.return_value = Orderbook(
            token_id="t",
            bids=tuple([
                OrderbookLevel(price=Decimal("0.60"), quantity=50),
                OrderbookLevel(price=Decimal("0.65"), quantity=100),
            ]),
            asks=tuple(),
        )
        fills = engine.sell_position("t", Side.YES, 10)
        assert len(fills) == 1
        assert fills[0].price == Decimal("0.65")
        assert fills[0].quantity == 10

    def test_walks_multiple_bid_levels(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(token_id="t", side=Side.YES, price=Decimal("0.50"), quantity=30)
        )
        mock_client.get_orderbook.return_value = Orderbook(
            token_id="t",
            bids=tuple([
                OrderbookLevel(price=Decimal("0.55"), quantity=10),
                OrderbookLevel(price=Decimal("0.60"), quantity=15),
            ]),
            asks=tuple(),
        )
        fills = engine.sell_position("t", Side.YES, 25)
        assert len(fills) == 2
        assert fills[0].price == Decimal("0.60")
        assert fills[0].quantity == 15
        assert fills[1].price == Decimal("0.55")
        assert fills[1].quantity == 10

    def test_partial_sell_leaves_remaining(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(token_id="t", side=Side.YES, price=Decimal("0.50"), quantity=20)
        )
        mock_client.get_orderbook.return_value = Orderbook(
            token_id="t",
            bids=tuple([OrderbookLevel(price=Decimal("0.55"), quantity=100)]),
            asks=tuple(),
        )
        fills = engine.sell_position("t", Side.YES, 5)
        assert len(fills) == 1
        assert fills[0].quantity == 5
        pos = engine.portfolio.get_position("t", Side.YES)
        assert pos is not None
        assert pos.quantity == 15

    def test_raises_on_no_position(self, engine, mock_client):
        with pytest.raises(ValueError, match="No position"):
            engine.sell_position("t", Side.YES, 10)

    def test_raises_on_exceeds_quantity(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(token_id="t", side=Side.YES, price=Decimal("0.50"), quantity=5)
        )
        with pytest.raises(ValueError, match="exceeds position"):
            engine.sell_position("t", Side.YES, 10)

    def test_empty_orderbook_no_fills(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(token_id="t", side=Side.YES, price=Decimal("0.50"), quantity=10)
        )
        mock_client.get_orderbook.return_value = Orderbook(
            token_id="t", bids=tuple(), asks=tuple()
        )
        fills = engine.sell_position("t", Side.YES, 5)
        assert fills == []
        pos = engine.portfolio.get_position("t", Side.YES)
        assert pos is not None
        assert pos.quantity == 10


class TestCheckSettlements:
    def test_settles_resolved_market(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(token_id="yes_tok", side=Side.YES, price=Decimal("0.60"), quantity=10)
        )
        settled_market = MagicMock()
        settled_market.closed = True
        settled_market.outcome_prices = (Decimal("1.00"), Decimal("0.00"))
        mock_client.get_market.return_value = settled_market

        engine.check_settlements({"yes_tok": "cond_id"})
        assert engine.portfolio.get_position("yes_tok", Side.YES) is None
        assert engine.portfolio.realized_pnl == Decimal("4.00")

    def test_skips_open_market(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(token_id="yes_tok", side=Side.YES, price=Decimal("0.60"), quantity=10)
        )
        open_market = MagicMock()
        open_market.closed = False
        mock_client.get_market.return_value = open_market

        engine.check_settlements({"yes_tok": "cond_id"})
        assert engine.portfolio.get_position("yes_tok", Side.YES) is not None
