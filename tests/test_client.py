"""Tests for Polymarket API client."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from polymarket_bot.client import PolymarketClient
from polymarket_bot.models import Market, Orderbook, PricePoint


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def client(mock_session):
    return PolymarketClient(session=mock_session)


class TestClientInit:
    def test_default_urls(self, client):
        assert "gamma-api.polymarket.com" in client.gamma_url
        assert "clob.polymarket.com" in client.clob_url

    def test_custom_urls(self, mock_session):
        c = PolymarketClient(
            session=mock_session,
            gamma_url="https://custom.gamma/",
            clob_url="https://custom.clob/",
        )
        assert c.gamma_url == "https://custom.gamma/"
        assert c.clob_url == "https://custom.clob/"

    def test_creates_session_if_none(self):
        c = PolymarketClient()
        assert c.session is not None


class TestGetMarkets:
    def test_returns_markets(self, client, mock_session, sample_markets_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_markets_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        markets = client.get_markets()

        assert len(markets) == 1
        assert isinstance(markets[0], Market)
        assert markets[0].condition_id == "0xabc123def456"

    def test_passes_params(self, client, mock_session, sample_markets_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_markets_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client.get_markets(limit=10, offset=5, active=True)

        args, kwargs = mock_session.get.call_args
        params = kwargs.get("params", {})
        assert params["limit"] == 10
        assert params["offset"] == 5
        assert params["active"] is True


class TestGetMarket:
    def test_returns_single_market(self, client, mock_session, sample_market_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_market_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        market = client.get_market("0xabc123def456")

        assert isinstance(market, Market)
        assert market.condition_id == "0xabc123def456"
        mock_session.get.assert_called_once()


class TestGetOrderbook:
    def test_returns_orderbook(self, client, mock_session, sample_orderbook_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_orderbook_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        ob = client.get_orderbook("token123")

        assert isinstance(ob, Orderbook)
        assert ob.token_id == "token123"
        assert len(ob.bids) == 3
        assert ob.bids[0].price == Decimal("0.63")


class TestGetPriceHistory:
    def test_returns_price_points(self, client, mock_session, sample_price_history_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_price_history_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        history = client.get_price_history("token123")

        assert len(history) == 5
        assert isinstance(history[0], PricePoint)
        assert history[0].price == Decimal("0.65")


class TestErrorHandling:
    def test_raises_on_http_error(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404 Not Found")
        mock_session.get.return_value = mock_resp

        with pytest.raises(Exception, match="404"):
            client.get_market("NONEXISTENT")
