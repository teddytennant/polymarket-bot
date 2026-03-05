"""Tests for domain models."""

from decimal import Decimal
import pytest

from polymarket_bot.models import (
    Market,
    Orderbook,
    OrderbookLevel,
    PricePoint,
    Order,
    Position,
    Fill,
    Side,
    OrderType,
    OrderStatus,
)


class TestEnums:
    def test_side_values(self):
        assert Side.YES.value == "yes"
        assert Side.NO.value == "no"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.CANCELLED.value == "cancelled"


class TestOrderbookLevel:
    def test_creation(self):
        level = OrderbookLevel(price=Decimal("0.65"), quantity=100)
        assert level.price == Decimal("0.65")
        assert level.quantity == 100

    def test_frozen(self):
        level = OrderbookLevel(price=Decimal("0.65"), quantity=100)
        with pytest.raises(AttributeError):
            level.price = Decimal("0.70")


class TestMarket:
    def test_from_api(self, sample_market_response):
        market = Market.from_api(sample_market_response)
        assert market.condition_id == "0xabc123def456"
        assert market.question == "Will Bitcoin hit $100k by March 2026?"
        assert market.yes_price == Decimal("0.65")
        assert market.no_price == Decimal("0.35")
        assert market.yes_token_id == "12345678"
        assert market.no_token_id == "87654321"
        assert market.active is True
        assert market.closed is False
        assert market.status == "active"

    def test_from_api_list_fields(self):
        """Test with already-parsed list fields (not JSON strings)."""
        data = {
            "conditionId": "0x123",
            "question": "Test",
            "slug": "test",
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["0.50", "0.50"],
            "clobTokenIds": ["111", "222"],
            "volume": 1000,
            "liquidity": 500,
            "active": True,
            "closed": False,
            "endDate": "",
            "description": "",
        }
        market = Market.from_api(data)
        assert market.yes_price == Decimal("0.50")
        assert market.yes_token_id == "111"

    def test_frozen(self, sample_market_response):
        market = Market.from_api(sample_market_response)
        with pytest.raises(AttributeError):
            market.condition_id = "new"

    def test_status_closed(self):
        data = {
            "conditionId": "0x1",
            "question": "T",
            "slug": "t",
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["1.00", "0.00"],
            "clobTokenIds": ["1", "2"],
            "volume": 0,
            "liquidity": 0,
            "active": False,
            "closed": True,
            "endDate": "",
            "description": "",
        }
        market = Market.from_api(data)
        assert market.status == "closed"


class TestOrderbook:
    def test_from_api(self, sample_orderbook_response):
        ob = Orderbook.from_api("token123", sample_orderbook_response)
        assert ob.token_id == "token123"
        assert len(ob.bids) == 3
        assert len(ob.asks) == 3

    def test_best_bid(self, sample_orderbook_response):
        ob = Orderbook.from_api("t", sample_orderbook_response)
        assert ob.best_bid == Decimal("0.65")

    def test_best_ask(self, sample_orderbook_response):
        ob = Orderbook.from_api("t", sample_orderbook_response)
        assert ob.best_ask == Decimal("0.67")

    def test_empty_orderbook(self):
        ob = Orderbook(token_id="t", bids=(), asks=())
        assert ob.best_bid is None
        assert ob.best_ask is None


class TestPricePoint:
    def test_from_api(self):
        data = {"t": 1709654321, "p": "0.65"}
        pp = PricePoint.from_api(data)
        assert pp.timestamp == 1709654321
        assert pp.price == Decimal("0.65")


class TestOrder:
    def test_creation(self):
        order = Order(
            token_id="t",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.65"),
            quantity=10,
            status=OrderStatus.PENDING,
        )
        assert order.token_id == "t"
        assert order.side == Side.YES
        assert order.price == Decimal("0.65")

    def test_market_order_no_price(self):
        order = Order(
            token_id="t",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=5,
            status=OrderStatus.PENDING,
        )
        assert order.price is None
        assert order.order_type == OrderType.MARKET


class TestPosition:
    def test_creation(self):
        pos = Position(
            token_id="t",
            side=Side.YES,
            quantity=10,
            avg_price=Decimal("0.65"),
        )
        assert pos.token_id == "t"
        assert pos.quantity == 10

    def test_cost_basis(self):
        pos = Position(
            token_id="t",
            side=Side.YES,
            quantity=10,
            avg_price=Decimal("0.65"),
        )
        assert pos.cost_basis == Decimal("6.50")


class TestFill:
    def test_creation(self):
        fill = Fill(
            token_id="t",
            side=Side.YES,
            price=Decimal("0.65"),
            quantity=10,
        )
        assert fill.token_id == "t"
        assert fill.total_cost == Decimal("6.50")

    def test_frozen(self):
        fill = Fill(
            token_id="t",
            side=Side.YES,
            price=Decimal("0.65"),
            quantity=10,
        )
        with pytest.raises(AttributeError):
            fill.price = Decimal("0.70")
