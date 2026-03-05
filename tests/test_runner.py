"""Tests for CLI entry point."""

import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from polymarket_bot.events import Event, EventBus, EventType
from polymarket_bot.models import (
    Fill,
    Market,
    Orderbook,
    OrderbookLevel,
    PricePoint,
    Side,
)
from polymarket_bot.portfolio import Portfolio
from polymarket_bot.runner import (
    build_parser,
    cmd_markets,
    cmd_run,
    cmd_status,
    format_event,
    print_portfolio_summary,
    run_cycle,
)


@pytest.fixture
def mock_client():
    return MagicMock()


def _make_market(**overrides):
    defaults = dict(
        condition_id="0x1", question="Test", slug="test-market", status="active",
        outcomes=("Yes", "No"), outcome_prices=(Decimal("0.65"), Decimal("0.35")),
        token_ids=("yes_tok", "no_tok"), volume=Decimal("1000"),
        liquidity=Decimal("500"), active=True, closed=False, end_date="", description="",
    )
    defaults.update(overrides)
    return Market(**defaults)


def _make_orderbook(token_id="yes_tok"):
    return Orderbook(
        token_id=token_id,
        bids=tuple([OrderbookLevel(Decimal("0.65"), 100)]),
        asks=tuple([OrderbookLevel(Decimal("0.67"), 120)]),
    )


class TestBuildParser:
    def test_run_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--interval", "30", "--balance", "5000"])
        assert args.command == "run"
        assert args.interval == 30
        assert args.balance == 5000

    def test_status_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["status", "--state-file", "/tmp/state.json"])
        assert args.command == "status"
        assert args.state_file == "/tmp/state.json"

    def test_markets_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["markets", "--limit", "5"])
        assert args.command == "markets"
        assert args.limit == 5

    def test_run_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.interval == 60
        assert args.balance == 10000
        assert args.state_file == "state.json"
        assert args.cycles == 0
        assert args.verbose is False

    def test_dashboard_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["dashboard", "--interval", "30"])
        assert args.command == "dashboard"
        assert args.interval == 30


class TestCmdMarkets:
    def test_lists_markets(self, mock_client, capsys):
        mock_client.get_markets.return_value = [_make_market()]
        cmd_markets(mock_client, active=True, limit=10)
        captured = capsys.readouterr()
        assert "test-market" in captured.out
        assert "Test" in captured.out


class TestCmdStatus:
    def test_shows_balance(self, tmp_path, capsys):
        p = Portfolio(initial_balance=Decimal("10000.00"))
        p.record_fill(Fill(token_id="t", side=Side.YES, price=Decimal("0.65"), quantity=10))
        state_file = tmp_path / "state.json"
        from polymarket_bot.persistence import save_state
        save_state(p, state_file)
        cmd_status(str(state_file))
        captured = capsys.readouterr()
        assert "9993.50" in captured.out
        assert "Return:" in captured.out

    def test_no_state_file(self, tmp_path, capsys):
        cmd_status(str(tmp_path / "nonexistent.json"))
        captured = capsys.readouterr()
        assert "No state file" in captured.out


class TestFormatEvent:
    def test_cycle_start(self):
        e = Event(EventType.CYCLE_START, time.time(), {"cycle": 3})
        line = format_event(e)
        assert "Cycle 3 started" in line

    def test_cycle_end(self):
        e = Event(EventType.CYCLE_END, time.time(), {
            "cycle": 3, "markets": 15, "signals": 2, "fills": 1,
        })
        line = format_event(e)
        assert "Cycle 3 complete" in line
        assert "15 markets" in line

    def test_cycle_error(self):
        e = Event(EventType.CYCLE_ERROR, time.time(), {"error": "connection timeout"})
        line = format_event(e)
        assert "ERROR" in line
        assert "connection timeout" in line

    def test_signal_generated(self):
        e = Event(EventType.SIGNAL_GENERATED, time.time(), {
            "slug": "test-market", "side": "yes", "price": "0.65", "quantity": 10,
        })
        line = format_event(e)
        assert "SIGNAL YES" in line
        assert "test-market" in line

    def test_order_filled(self):
        e = Event(EventType.ORDER_FILLED, time.time(), {
            "slug": "test-market", "side": "yes", "quantity": 10, "total_cost": "6.50",
        })
        line = format_event(e)
        assert "FILLED YES" in line
        assert "10 contracts" in line

    def test_market_scanned_hidden_by_default(self):
        e = Event(EventType.MARKET_SCANNED, time.time(), {
            "slug": "test", "yes_price": "0.65", "no_price": "0.35", "signal": None,
        })
        assert format_event(e, verbose=False) is None

    def test_market_scanned_shown_with_verbose(self):
        e = Event(EventType.MARKET_SCANNED, time.time(), {
            "slug": "test", "yes_price": "0.65", "no_price": "0.35", "signal": None,
        })
        line = format_event(e, verbose=True)
        assert "test" in line
        assert "0.65" in line

    def test_cycle_end_with_exits(self):
        e = Event(EventType.CYCLE_END, time.time(), {
            "cycle": 1, "markets": 5, "signals": 1, "fills": 1, "exits": 2,
        })
        line = format_event(e)
        assert "2 exits" in line

    def test_cycle_end_without_exits(self):
        e = Event(EventType.CYCLE_END, time.time(), {
            "cycle": 1, "markets": 5, "signals": 1, "fills": 1, "exits": 0,
        })
        line = format_event(e)
        assert "exits" not in line


class TestRunCycle:
    def test_evaluates_strategy_for_each_market(self, mock_client):
        portfolio = Portfolio()
        strategy = MagicMock()
        market = _make_market()
        strategy.select_markets.return_value = [market]
        strategy.evaluate.return_value = None
        mock_client.get_markets.return_value = [market]
        mock_client.get_orderbook.return_value = _make_orderbook()
        mock_client.get_price_history.return_value = []

        run_cycle(mock_client, portfolio, strategy)

        strategy.evaluate.assert_called_once()

    def test_emits_cycle_start_and_end(self, mock_client):
        strategy = MagicMock()
        strategy.select_markets.return_value = [_make_market()]
        strategy.evaluate.return_value = None
        mock_client.get_markets.return_value = [_make_market()]
        mock_client.get_orderbook.return_value = _make_orderbook()
        mock_client.get_price_history.return_value = []

        bus = EventBus()
        run_cycle(mock_client, Portfolio(), strategy, event_bus=bus, cycle_number=1)

        events, _ = bus.drain_from(0)
        types = [e.event_type for e in events]
        assert EventType.CYCLE_START in types
        assert EventType.CYCLE_END in types


class TestCmdRun:
    def test_runs_fixed_cycles(self, mock_client, tmp_path, capsys):
        market = _make_market()
        strategy = MagicMock()
        strategy.select_markets.return_value = [market]
        strategy.evaluate.return_value = None
        mock_client.get_markets.return_value = [market]
        mock_client.get_orderbook.return_value = _make_orderbook()
        mock_client.get_price_history.return_value = []

        state_path = tmp_path / "state.json"
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        cmd_run(mock_client, state_path, portfolio, strategy, interval=0, max_cycles=2)
        out = capsys.readouterr().out
        assert "Cycle 1 started" in out
        assert "Cycle 2 started" in out
        assert "State saved" in out

    def test_handles_cycle_error(self, mock_client, tmp_path, capsys):
        strategy = MagicMock()
        mock_client.get_markets.side_effect = Exception("API down")

        state_path = tmp_path / "state.json"
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        cmd_run(mock_client, state_path, portfolio, strategy, interval=0, max_cycles=1)
        out = capsys.readouterr().out
        assert "ERROR" in out
        assert "API down" in out


class TestExitMonitoring:
    def test_take_profit_triggers_exit(self, mock_client):
        market = _make_market()
        strategy = MagicMock()
        strategy.select_markets.return_value = [market]
        strategy.evaluate.return_value = None
        mock_client.get_markets.return_value = [market]
        mock_client.get_price_history.return_value = []

        portfolio = Portfolio(initial_balance=Decimal("10000"))
        portfolio.record_fill(
            Fill(token_id="pos_tok", side=Side.YES, price=Decimal("0.50"), quantity=10)
        )

        def mock_orderbook(token_id):
            if token_id == "pos_tok":
                return Orderbook(
                    token_id="pos_tok",
                    bids=tuple([OrderbookLevel(Decimal("0.55"), 50)]),
                    asks=tuple(),
                )
            return _make_orderbook(token_id)
        mock_client.get_orderbook.side_effect = mock_orderbook

        bus = EventBus()
        run_cycle(
            mock_client, portfolio, strategy, event_bus=bus, cycle_number=1,
            take_profit=Decimal("0.04"),
        )

        events, _ = bus.drain_from(0)
        types = [e.event_type for e in events]
        assert EventType.EXIT_SIGNAL in types
        exit_ev = [e for e in events if e.event_type == EventType.EXIT_SIGNAL][0]
        assert exit_ev.data["reason"] == "take_profit"

    def test_no_exit_when_thresholds_disabled(self, mock_client):
        market = _make_market()
        strategy = MagicMock()
        strategy.select_markets.return_value = [market]
        strategy.evaluate.return_value = None
        mock_client.get_markets.return_value = [market]
        mock_client.get_price_history.return_value = []

        portfolio = Portfolio(initial_balance=Decimal("10000"))
        portfolio.record_fill(
            Fill(token_id="pos_tok", side=Side.YES, price=Decimal("0.50"), quantity=10)
        )

        def mock_orderbook(token_id):
            if token_id == "pos_tok":
                return Orderbook(
                    token_id="pos_tok",
                    bids=tuple([OrderbookLevel(Decimal("0.90"), 50)]),
                    asks=tuple(),
                )
            return _make_orderbook(token_id)
        mock_client.get_orderbook.side_effect = mock_orderbook

        bus = EventBus()
        run_cycle(mock_client, portfolio, strategy, event_bus=bus, cycle_number=1)

        events, _ = bus.drain_from(0)
        types = [e.event_type for e in events]
        assert EventType.EXIT_SIGNAL not in types


class TestExitMonitoringParser:
    def test_run_take_profit_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--take-profit", "0.05"])
        assert args.take_profit == 0.05

    def test_run_stop_loss_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--stop-loss", "0.10"])
        assert args.stop_loss == 0.10

    def test_run_defaults_disabled(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.take_profit == 0
        assert args.stop_loss == 0
