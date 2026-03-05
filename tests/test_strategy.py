"""Tests for strategy ABC and MeanReversionStrategy."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from polymarket_bot.models import (
    Market,
    Orderbook,
    OrderbookLevel,
    OrderType,
    PricePoint,
    Side,
)
from polymarket_bot.portfolio import Portfolio
from polymarket_bot.strategy import MeanReversionStrategy, Strategy, TradeSignal


@pytest.fixture
def portfolio():
    return Portfolio()


@pytest.fixture
def sample_market():
    return Market(
        condition_id="0x1",
        question="Test",
        slug="test",
        status="active",
        outcomes=("Yes", "No"),
        outcome_prices=(Decimal("0.65"), Decimal("0.35")),
        token_ids=("yes_tok", "no_tok"),
        volume=Decimal("1000"),
        liquidity=Decimal("500"),
        active=True,
        closed=False,
        end_date="",
        description="",
    )


@pytest.fixture
def yes_orderbook():
    return Orderbook(
        token_id="yes_tok",
        bids=tuple([OrderbookLevel(Decimal("0.65"), 100)]),
        asks=tuple([OrderbookLevel(Decimal("0.67"), 120)]),
    )


@pytest.fixture
def no_orderbook():
    return Orderbook(
        token_id="no_tok",
        bids=tuple([OrderbookLevel(Decimal("0.33"), 100)]),
        asks=tuple([OrderbookLevel(Decimal("0.35"), 120)]),
    )


class TestTradeSignal:
    def test_creation(self):
        sig = TradeSignal(
            token_id="t",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.65"),
            quantity=10,
        )
        assert sig.token_id == "t"
        assert sig.side == Side.YES
        assert sig.price == Decimal("0.65")

    def test_frozen(self):
        sig = TradeSignal(
            token_id="t",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=5,
        )
        with pytest.raises(AttributeError):
            sig.token_id = "x"


class TestStrategyABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Strategy()

    def test_subclass_must_implement_evaluate(self):
        class BadStrategy(Strategy):
            def select_markets(self, markets):
                return markets

        with pytest.raises(TypeError):
            BadStrategy()


class TestMeanReversionStrategy:
    def test_buy_yes_when_below_mean(self, portfolio, sample_market, yes_orderbook, no_orderbook):
        strategy = MeanReversionStrategy(
            window=3,
            threshold=Decimal("0.05"),
            order_quantity=10,
        )
        # Recent prices at higher levels -> mean is high, current ask is low
        history = [
            PricePoint(timestamp=3, price=Decimal("0.80")),
            PricePoint(timestamp=2, price=Decimal("0.78")),
            PricePoint(timestamp=1, price=Decimal("0.75")),
        ]
        # Mean = 0.7767, yes_ask = 0.67, 0.67 < 0.7767 - 0.05 -> BUY YES
        signal = strategy.evaluate(sample_market, yes_orderbook, no_orderbook, history, portfolio)
        assert signal is not None
        assert signal.side == Side.YES
        assert signal.quantity == 10

    def test_buy_no_when_above_mean(self, portfolio, no_orderbook):
        strategy = MeanReversionStrategy(
            window=3,
            threshold=Decimal("0.05"),
            order_quantity=10,
        )
        high_market = Market(
            condition_id="0x1",
            question="Test",
            slug="test",
            status="active",
            outcomes=("Yes", "No"),
            outcome_prices=(Decimal("0.85"), Decimal("0.15")),
            token_ids=("yes_tok", "no_tok"),
            volume=Decimal("1000"),
            liquidity=Decimal("500"),
            active=True,
            closed=False,
            end_date="",
            description="",
        )
        yes_ob = Orderbook(
            token_id="yes_tok",
            bids=tuple([OrderbookLevel(Decimal("0.85"), 100)]),
            asks=tuple([OrderbookLevel(Decimal("0.87"), 120)]),
        )
        history = [
            PricePoint(timestamp=3, price=Decimal("0.70")),
            PricePoint(timestamp=2, price=Decimal("0.72")),
            PricePoint(timestamp=1, price=Decimal("0.68")),
        ]
        # Mean = 0.70, yes_price = 0.85, 0.85 > 0.70 + 0.05 -> BUY NO
        signal = strategy.evaluate(high_market, yes_ob, no_orderbook, history, portfolio)
        assert signal is not None
        assert signal.side == Side.NO

    def test_no_signal_within_threshold(self, portfolio, sample_market, yes_orderbook, no_orderbook):
        strategy = MeanReversionStrategy(
            window=3,
            threshold=Decimal("0.05"),
            order_quantity=10,
        )
        history = [
            PricePoint(timestamp=3, price=Decimal("0.66")),
            PricePoint(timestamp=2, price=Decimal("0.64")),
            PricePoint(timestamp=1, price=Decimal("0.65")),
        ]
        signal = strategy.evaluate(sample_market, yes_orderbook, no_orderbook, history, portfolio)
        assert signal is None

    def test_insufficient_history(self, portfolio, sample_market, yes_orderbook, no_orderbook):
        strategy = MeanReversionStrategy(window=5, threshold=Decimal("0.05"), order_quantity=10)
        history = [PricePoint(timestamp=1, price=Decimal("0.70"))]
        signal = strategy.evaluate(sample_market, yes_orderbook, no_orderbook, history, portfolio)
        assert signal is None

    def test_select_markets_filters_active(self):
        strategy = MeanReversionStrategy(window=3, threshold=Decimal("0.05"), order_quantity=10)
        active = Market(
            condition_id="0x1", question="A", slug="a", status="active",
            outcomes=("Yes", "No"), outcome_prices=(Decimal("0.50"), Decimal("0.50")),
            token_ids=("1", "2"), volume=Decimal("100"), liquidity=Decimal("50"),
            active=True, closed=False, end_date="", description="",
        )
        closed = Market(
            condition_id="0x2", question="B", slug="b", status="closed",
            outcomes=("Yes", "No"), outcome_prices=(Decimal("1.00"), Decimal("0.00")),
            token_ids=("3", "4"), volume=Decimal("100"), liquidity=Decimal("50"),
            active=False, closed=True, end_date="", description="",
        )
        selected = strategy.select_markets([active, closed])
        assert len(selected) == 1
        assert selected[0].condition_id == "0x1"

    def test_select_markets_filters_low_volume(self):
        strategy = MeanReversionStrategy(
            window=3, threshold=Decimal("0.05"), order_quantity=10, min_volume=500,
        )
        low_vol = Market(
            condition_id="0x1", question="A", slug="a", status="active",
            outcomes=("Yes", "No"), outcome_prices=(Decimal("0.50"), Decimal("0.50")),
            token_ids=("1", "2"), volume=Decimal("100"), liquidity=Decimal("50"),
            active=True, closed=False, end_date="", description="",
        )
        high_vol = Market(
            condition_id="0x2", question="B", slug="b", status="active",
            outcomes=("Yes", "No"), outcome_prices=(Decimal("0.50"), Decimal("0.50")),
            token_ids=("3", "4"), volume=Decimal("1000"), liquidity=Decimal("500"),
            active=True, closed=False, end_date="", description="",
        )
        selected = strategy.select_markets([low_vol, high_vol])
        assert len(selected) == 1
        assert selected[0].condition_id == "0x2"

    def test_select_markets_requires_token_ids(self):
        strategy = MeanReversionStrategy(window=3, threshold=Decimal("0.05"), order_quantity=10)
        no_tokens = Market(
            condition_id="0x1", question="A", slug="a", status="active",
            outcomes=("Yes", "No"), outcome_prices=(Decimal("0.50"), Decimal("0.50")),
            token_ids=(), volume=Decimal("100"), liquidity=Decimal("50"),
            active=True, closed=False, end_date="", description="",
        )
        selected = strategy.select_markets([no_tokens])
        assert len(selected) == 0
