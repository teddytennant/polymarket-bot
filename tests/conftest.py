"""Shared fixtures with realistic Polymarket API response data."""

import pytest
from decimal import Decimal


@pytest.fixture
def sample_market_response():
    """Raw Gamma API response for a single market."""
    return {
        "conditionId": "0xabc123def456",
        "question": "Will Bitcoin hit $100k by March 2026?",
        "slug": "will-bitcoin-hit-100k-march-2026",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.65", "0.35"]',
        "clobTokenIds": '["12345678", "87654321"]',
        "volume": 250000.0,
        "liquidity": 50000.0,
        "active": True,
        "closed": False,
        "endDate": "2026-03-31T23:59:59Z",
        "description": "Resolves Yes if BTC >= $100,000",
    }


@pytest.fixture
def sample_markets_response(sample_market_response):
    """Raw Gamma API response for market listing."""
    return [sample_market_response]


@pytest.fixture
def sample_orderbook_response():
    """Raw CLOB API response for an orderbook."""
    return {
        "bids": [
            {"price": "0.63", "size": "200"},
            {"price": "0.60", "size": "150"},
            {"price": "0.65", "size": "100"},
        ],
        "asks": [
            {"price": "0.67", "size": "120"},
            {"price": "0.70", "size": "80"},
            {"price": "0.72", "size": "200"},
        ],
    }


@pytest.fixture
def sample_price_history_response():
    """Raw CLOB API response for price history."""
    return {
        "history": [
            {"t": 1709654321, "p": "0.65"},
            {"t": 1709650721, "p": "0.66"},
            {"t": 1709647121, "p": "0.64"},
            {"t": 1709643521, "p": "0.63"},
            {"t": 1709639921, "p": "0.67"},
        ]
    }
