"""Thin requests wrapper for Polymarket public APIs (Gamma + CLOB)."""

from __future__ import annotations

import time
from typing import Optional

import requests

from polymarket_bot.models import Market, Orderbook, PricePoint

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

# Retry config
_MAX_RETRIES = 4
_BASE_DELAY = 1.0  # seconds
_MAX_DELAY = 30.0  # seconds


class PolymarketClient:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        gamma_url: str = GAMMA_URL,
        clob_url: str = CLOB_URL,
        max_retries: int = _MAX_RETRIES,
        base_delay: float = _BASE_DELAY,
    ):
        self.session = session or requests.Session()
        self.gamma_url = gamma_url
        self.clob_url = clob_url
        self.max_retries = max_retries
        self.base_delay = base_delay

    def _get(self, url: str, params: Optional[dict] = None) -> dict | list:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=10)
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        delay = min(float(retry_after), _MAX_DELAY)
                    else:
                        delay = min(self.base_delay * (2 ** attempt), _MAX_DELAY)
                    if attempt < self.max_retries:
                        time.sleep(delay)
                        continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.ConnectionError as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = min(self.base_delay * (2 ** attempt), _MAX_DELAY)
                    time.sleep(delay)
                    continue
            except requests.exceptions.HTTPError:
                raise
        raise last_exc  # type: ignore[misc]

    # --- Gamma API: market discovery ---

    def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active: Optional[bool] = None,
        closed: Optional[bool] = None,
        order: str = "volume_24hr",
        ascending: bool = False,
    ) -> list[Market]:
        params: dict = {
            "limit": limit,
            "offset": offset,
            "order": order,
            "ascending": ascending,
        }
        if active is not None:
            params["active"] = active
        if closed is not None:
            params["closed"] = closed

        data = self._get(f"{self.gamma_url}/markets", params=params)
        if not isinstance(data, list):
            data = data.get("markets", data) if isinstance(data, dict) else []
        return [Market.from_api(m) for m in data]

    def get_market(self, condition_id: str) -> Market:
        data = self._get(f"{self.gamma_url}/markets/{condition_id}")
        if isinstance(data, list):
            data = data[0]
        return Market.from_api(data)

    def get_market_by_slug(self, slug: str) -> Market:
        data = self._get(f"{self.gamma_url}/markets/slug/{slug}")
        if isinstance(data, list):
            data = data[0]
        return Market.from_api(data)

    # --- CLOB API: orderbook and pricing ---

    def get_orderbook(self, token_id: str) -> Orderbook:
        data = self._get(f"{self.clob_url}/book", params={"token_id": token_id})
        return Orderbook.from_api(token_id, data)

    def get_midpoint(self, token_id: str) -> Optional[str]:
        data = self._get(f"{self.clob_url}/midpoint", params={"token_id": token_id})
        return data.get("mid") if isinstance(data, dict) else None

    def get_price(self, token_id: str, side: str = "BUY") -> Optional[str]:
        data = self._get(
            f"{self.clob_url}/price",
            params={"token_id": token_id, "side": side},
        )
        return data.get("price") if isinstance(data, dict) else None

    def get_last_trade_price(self, token_id: str) -> Optional[str]:
        data = self._get(
            f"{self.clob_url}/last-trade-price",
            params={"token_id": token_id},
        )
        return data.get("price") if isinstance(data, dict) else None

    def get_price_history(
        self,
        token_id: str,
        interval: str = "1d",
        fidelity: int = 60,
    ) -> list[PricePoint]:
        data = self._get(
            f"{self.clob_url}/prices-history",
            params={
                "market": token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
        )
        if isinstance(data, dict):
            history = data.get("history", [])
        else:
            history = data if isinstance(data, list) else []
        return [PricePoint.from_api(p) for p in history]
