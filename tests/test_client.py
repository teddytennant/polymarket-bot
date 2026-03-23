"""Tests for Polymarket API client."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import requests

from polymarket_bot.client import PolymarketClient
from polymarket_bot.models import Market, Orderbook, PricePoint


def _ok_response(json_data):
    """Helper: build a mock response with status_code=200."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def client(mock_session):
    return PolymarketClient(session=mock_session, max_retries=0)


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
        mock_session.get.return_value = _ok_response(sample_markets_response)

        markets = client.get_markets()

        assert len(markets) == 1
        assert isinstance(markets[0], Market)
        assert markets[0].condition_id == "0xabc123def456"

    def test_passes_params(self, client, mock_session, sample_markets_response):
        mock_session.get.return_value = _ok_response(sample_markets_response)

        client.get_markets(limit=10, offset=5, active=True)

        args, kwargs = mock_session.get.call_args
        params = kwargs.get("params", {})
        assert params["limit"] == 10
        assert params["offset"] == 5
        assert params["active"] is True


class TestGetMarket:
    def test_returns_single_market(self, client, mock_session, sample_market_response):
        mock_session.get.return_value = _ok_response(sample_market_response)

        market = client.get_market("0xabc123def456")

        assert isinstance(market, Market)
        assert market.condition_id == "0xabc123def456"
        mock_session.get.assert_called_once()


class TestGetOrderbook:
    def test_returns_orderbook(self, client, mock_session, sample_orderbook_response):
        mock_session.get.return_value = _ok_response(sample_orderbook_response)

        ob = client.get_orderbook("token123")

        assert isinstance(ob, Orderbook)
        assert ob.token_id == "token123"
        assert len(ob.bids) == 3
        assert ob.bids[0].price == Decimal("0.63")


class TestGetPriceHistory:
    def test_returns_price_points(self, client, mock_session, sample_price_history_response):
        mock_session.get.return_value = _ok_response(sample_price_history_response)

        history = client.get_price_history("token123")

        assert len(history) == 5
        assert isinstance(history[0], PricePoint)
        assert history[0].price == Decimal("0.65")


class TestErrorHandling:
    def test_raises_on_http_error(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_session.get.return_value = mock_resp

        with pytest.raises(requests.exceptions.HTTPError, match="404"):
            client.get_market("NONEXISTENT")


class TestRetryBackoff:
    @patch("polymarket_bot.client.time.sleep")
    def test_retries_on_429(self, mock_sleep, mock_session, sample_market_response):
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}

        ok = _ok_response(sample_market_response)

        mock_session.get.side_effect = [rate_limited, ok]
        c = PolymarketClient(session=mock_session, max_retries=2, base_delay=1.0)

        market = c.get_market("0xabc123def456")
        assert market.condition_id == "0xabc123def456"
        assert mock_session.get.call_count == 2
        mock_sleep.assert_called_once_with(1.0)

    @patch("polymarket_bot.client.time.sleep")
    def test_respects_retry_after_header(self, mock_sleep, mock_session, sample_market_response):
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "5"}

        ok = _ok_response(sample_market_response)

        mock_session.get.side_effect = [rate_limited, ok]
        c = PolymarketClient(session=mock_session, max_retries=2, base_delay=1.0)

        c.get_market("0xabc123def456")
        mock_sleep.assert_called_once_with(5.0)

    @patch("polymarket_bot.client.time.sleep")
    def test_exponential_backoff_on_429(self, mock_sleep, mock_session, sample_market_response):
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}

        ok = _ok_response(sample_market_response)

        mock_session.get.side_effect = [rate_limited, rate_limited, ok]
        c = PolymarketClient(session=mock_session, max_retries=3, base_delay=1.0)

        c.get_market("0xabc123def456")
        assert mock_sleep.call_count == 2
        # First retry: 1.0 * 2^0 = 1.0, second: 1.0 * 2^1 = 2.0
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("polymarket_bot.client.time.sleep")
    def test_raises_after_max_retries_exhausted(self, mock_sleep, mock_session):
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}
        rate_limited.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Too Many Requests")

        mock_session.get.return_value = rate_limited
        c = PolymarketClient(session=mock_session, max_retries=2, base_delay=0.1)

        with pytest.raises(requests.exceptions.HTTPError, match="429"):
            c.get_market("0xabc123def456")
        # Initial + 2 retries = 3 calls
        assert mock_session.get.call_count == 3

    @patch("polymarket_bot.client.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep, mock_session, sample_market_response):
        ok = _ok_response(sample_market_response)
        mock_session.get.side_effect = [
            requests.exceptions.ConnectionError("Connection reset"),
            ok,
        ]
        c = PolymarketClient(session=mock_session, max_retries=2, base_delay=1.0)

        market = c.get_market("0xabc123def456")
        assert market.condition_id == "0xabc123def456"
        assert mock_session.get.call_count == 2
