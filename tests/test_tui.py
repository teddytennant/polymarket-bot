"""Tests for TUI dashboard."""

import time
from decimal import Decimal
from unittest.mock import patch

import pytest

from polymarket_bot.events import EventBus, EventType
from polymarket_bot.tui import DashboardApp, HeaderBar


class TestHeaderBar:
    def test_update_stats_positive_pnl(self):
        bar = HeaderBar()
        bar.update_stats(
            balance=Decimal("10250.00"),
            initial_balance=Decimal("10000.00"),
            realized_pnl=Decimal("250.00"),
            cycle=5,
            start_time=time.time() - 3661,
        )
        text = str(bar.render())
        assert "$10250.00" in text
        assert "+$250.00" in text
        assert "+2.50%" in text
        assert "Cycle: 5" in text

    def test_update_stats_negative_pnl(self):
        bar = HeaderBar()
        bar.update_stats(
            balance=Decimal("9800.00"),
            initial_balance=Decimal("10000.00"),
            realized_pnl=Decimal("-200.00"),
            cycle=3,
            start_time=time.time(),
        )
        text = str(bar.render())
        assert "$9800.00" in text
        assert "-$200.00" in text
        assert "-2.00%" in text


class TestDashboardAppCompose:
    @pytest.mark.asyncio
    async def test_widgets_present(self):
        app = DashboardApp(interval=60, balance=10000)
        with patch.object(DashboardApp, "_trading_loop"):
            async with app.run_test(size=(120, 40)) as pilot:
                assert app.query_one("#header-bar", HeaderBar) is not None
                assert app.query_one("#positions") is not None
                assert app.query_one("#scanner") is not None
                assert app.query_one("#activity") is not None

    @pytest.mark.asyncio
    async def test_positions_table_has_columns(self):
        app = DashboardApp(interval=60, balance=10000)
        with patch.object(DashboardApp, "_trading_loop"):
            async with app.run_test(size=(120, 40)) as pilot:
                from textual.widgets import DataTable
                pos = app.query_one("#positions", DataTable)
                col_labels = [str(c.label) for c in pos.columns.values()]
                assert "Token" in col_labels
                assert "Side" in col_labels
                assert "Qty" in col_labels
                assert "Unrealized" in col_labels

    @pytest.mark.asyncio
    async def test_scanner_table_has_columns(self):
        app = DashboardApp(interval=60, balance=10000)
        with patch.object(DashboardApp, "_trading_loop"):
            async with app.run_test(size=(120, 40)) as pilot:
                from textual.widgets import DataTable
                scan = app.query_one("#scanner", DataTable)
                col_labels = [str(c.label) for c in scan.columns.values()]
                assert "Market" in col_labels
                assert "Yes" in col_labels
                assert "No" in col_labels
                assert "Signal" in col_labels


class TestDashboardKeybindings:
    @pytest.mark.asyncio
    async def test_pause_resume(self):
        app = DashboardApp(interval=60, balance=10000)
        with patch.object(DashboardApp, "_trading_loop"):
            async with app.run_test(size=(120, 40)) as pilot:
                assert app._paused.is_set()

                await pilot.press("p")
                assert not app._paused.is_set()

                await pilot.press("p")
                assert app._paused.is_set()


class TestDashboardRefresh:
    @pytest.mark.asyncio
    async def test_refresh_processes_events(self):
        app = DashboardApp(interval=60, balance=10000)
        with patch.object(DashboardApp, "_trading_loop"):
            async with app.run_test(size=(120, 40)) as pilot:
                app._event_bus.emit(EventType.CYCLE_START, cycle=1)
                app._event_bus.emit(
                    EventType.MARKET_SCANNED,
                    slug="test-market",
                    yes_price="0.65",
                    no_price="0.35",
                    signal=None,
                )
                app._event_bus.emit(
                    EventType.CYCLE_END,
                    cycle=1,
                    markets=1,
                    signals=0,
                    fills=0,
                )

                app._refresh_ui()
                await pilot.pause()

                from textual.widgets import DataTable
                scan = app.query_one("#scanner", DataTable)
                assert scan.row_count == 1
