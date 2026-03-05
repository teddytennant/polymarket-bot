"""Tests for JSON save/load of portfolio state."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from polymarket_bot.models import Fill, Side
from polymarket_bot.persistence import load_state, save_state
from polymarket_bot.portfolio import Portfolio


@pytest.fixture
def tmp_state_file(tmp_path):
    return tmp_path / "state.json"


class TestSaveState:
    def test_creates_file(self, tmp_state_file):
        p = Portfolio()
        save_state(p, tmp_state_file)
        assert tmp_state_file.exists()

    def test_valid_json(self, tmp_state_file):
        p = Portfolio()
        save_state(p, tmp_state_file)
        data = json.loads(tmp_state_file.read_text())
        assert "balance" in data
        assert "positions" in data

    def test_decimal_as_string(self, tmp_state_file):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.65"), quantity=10))
        save_state(p, tmp_state_file)
        data = json.loads(tmp_state_file.read_text())
        assert data["balance"] == "9993.50"
        assert isinstance(data["balance"], str)

    def test_positions_saved(self, tmp_state_file):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.65"), quantity=10))
        save_state(p, tmp_state_file)
        data = json.loads(tmp_state_file.read_text())
        assert len(data["positions"]) == 1
        assert data["positions"][0]["token_id"] == "t"
        assert data["positions"][0]["side"] == "yes"


class TestLoadState:
    def test_loads_portfolio(self, tmp_state_file):
        p = Portfolio()
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.65"), quantity=10))
        save_state(p, tmp_state_file)

        loaded = load_state(tmp_state_file)
        assert loaded.balance == p.balance
        pos = loaded.get_position("t", Side.YES)
        assert pos is not None
        assert pos.quantity == 10

    def test_returns_none_for_missing_file(self, tmp_path):
        result = load_state(tmp_path / "nonexistent.json")
        assert result is None

    def test_returns_none_for_invalid_json(self, tmp_state_file):
        tmp_state_file.write_text("not json{{{")
        result = load_state(tmp_state_file)
        assert result is None


class TestRoundtrip:
    def test_full_roundtrip(self, tmp_state_file):
        p = Portfolio(initial_balance=Decimal("5000.00"))
        p.record_fill(Fill(token_id="a", side=Side.YES, price=Decimal("0.70"), quantity=20))
        p.record_fill(Fill(token_id="b", side=Side.NO, price=Decimal("0.40"), quantity=15))
        p.close_position("a", Side.YES, close_price=Decimal("0.80"), quantity=5)

        save_state(p, tmp_state_file)
        loaded = load_state(tmp_state_file)

        assert loaded.balance == p.balance
        assert loaded.initial_balance == p.initial_balance
        assert loaded.realized_pnl == p.realized_pnl
        assert loaded.get_position("a", Side.YES).quantity == 15
        assert loaded.get_position("b", Side.NO).quantity == 15

    def test_overwrites_existing_file(self, tmp_state_file):
        p1 = Portfolio()
        save_state(p1, tmp_state_file)

        p2 = Portfolio(initial_balance=Decimal("20000.00"))
        save_state(p2, tmp_state_file)

        loaded = load_state(tmp_state_file)
        assert loaded.initial_balance == Decimal("20000.00")
