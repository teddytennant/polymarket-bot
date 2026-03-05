"""TUI dashboard for polymarket-bot using Textual."""

from __future__ import annotations

import time
import threading
from decimal import Decimal
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from polymarket_bot.client import PolymarketClient
from polymarket_bot.events import EventBus, EventType
from polymarket_bot.models import Side
from polymarket_bot.persistence import load_state, save_state
from polymarket_bot.portfolio import Portfolio
from polymarket_bot.strategy import MeanReversionStrategy


class HeaderBar(Static):
    """Top bar showing balance, P&L, return%, cycle#, and uptime."""

    def update_stats(
        self,
        balance: Decimal,
        initial_balance: Decimal,
        realized_pnl: Decimal,
        cycle: int,
        start_time: float,
    ) -> None:
        ret = (
            (balance - initial_balance) / initial_balance * 100
            if initial_balance
            else Decimal("0")
        )
        pnl_sign = "+" if realized_pnl >= 0 else "-"
        ret_sign = "+" if ret >= 0 else "-"
        realized_pnl = abs(realized_pnl)
        ret = abs(ret)
        elapsed = int(time.time() - start_time)
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        uptime = f"{hours}h{minutes:02d}m{seconds:02d}s"

        self.update(
            f" Balance: ${balance:.2f} "
            f"| P&L: {pnl_sign}${realized_pnl:.2f} "
            f"| Return: {ret_sign}{ret:.2f}% "
            f"| Cycle: {cycle} "
            f"| Uptime: {uptime}"
        )


class DashboardApp(App):
    """Textual TUI dashboard for polymarket-bot."""

    TITLE = "polymarket-bot Dashboard"

    CSS = """
    HeaderBar {
        dock: top;
        height: 1;
        background: $accent;
        color: $text;
        text-style: bold;
    }
    #positions {
        width: 1fr;
        height: 100%;
    }
    #scanner {
        width: 1fr;
        height: 100%;
    }
    #tables {
        height: 1fr;
    }
    #activity {
        height: 12;
        border-top: solid $accent;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "toggle_pause", "Pause/Resume"),
    ]

    def __init__(
        self,
        interval: int = 60,
        balance: int = 10000,
        state_file: str = "state.json",
        threshold: Decimal = Decimal("0.05"),
        order_quantity: int = 10,
        window: int = 10,
        min_volume: int = 0,
        take_profit: Decimal = Decimal("0"),
        stop_loss: Decimal = Decimal("0"),
    ):
        super().__init__()
        self._interval = interval
        self._initial_balance = balance
        self._state_file = state_file
        self._threshold = threshold
        self._order_quantity = order_quantity
        self._window = window
        self._min_volume = min_volume
        self._take_profit = take_profit
        self._stop_loss = stop_loss
        self._event_bus = EventBus()
        self._cursor = 0
        self._cycle_number = 0
        self._start_time = time.time()
        self._paused = threading.Event()
        self._paused.set()  # starts unpaused
        self._market_prices: dict[str, tuple[str, str]] = {}
        self._portfolio: Portfolio | None = None
        self._should_stop = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header()
        yield HeaderBar(id="header-bar")
        with Horizontal(id="tables"):
            yield DataTable(id="positions")
            yield DataTable(id="scanner")
        yield RichLog(id="activity", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        pos_table = self.query_one("#positions", DataTable)
        pos_table.add_columns("Token", "Side", "Qty", "Avg", "Unrealized")

        scan_table = self.query_one("#scanner", DataTable)
        scan_table.add_columns("Market", "Yes", "No", "Signal")

        state_path = Path(self._state_file)
        self._portfolio = load_state(state_path)
        if self._portfolio is None:
            self._portfolio = Portfolio(initial_balance=Decimal(self._initial_balance))

        self._refresh_header()

        self.run_worker(self._trading_loop, thread=True, exclusive=True)
        self.set_interval(0.5, self._refresh_ui)

    def on_unmount(self) -> None:
        self._should_stop.set()
        self._paused.set()

    def _trading_loop(self) -> None:
        from polymarket_bot.runner import run_cycle

        client = PolymarketClient()
        strategy = MeanReversionStrategy(
            window=self._window,
            threshold=self._threshold,
            order_quantity=self._order_quantity,
            min_volume=self._min_volume,
        )
        state_path = Path(self._state_file)

        while not self._should_stop.is_set():
            self._paused.wait()
            if self._should_stop.is_set():
                break

            self._cycle_number += 1
            try:
                run_cycle(
                    client,
                    self._portfolio,
                    strategy,
                    event_bus=self._event_bus,
                    cycle_number=self._cycle_number,
                    take_profit=self._take_profit,
                    stop_loss=self._stop_loss,
                )
                save_state(self._portfolio, state_path)
            except Exception as e:
                self._event_bus.emit(
                    EventType.CYCLE_ERROR,
                    cycle=self._cycle_number,
                    error=str(e),
                )

            for _ in range(self._interval * 10):
                if self._should_stop.is_set():
                    return
                if not self._paused.is_set():
                    break
                time.sleep(0.1)

    def _refresh_ui(self) -> None:
        events, self._cursor = self._event_bus.drain_from(self._cursor)
        activity = self.query_one("#activity", RichLog)
        scan_table = self.query_one("#scanner", DataTable)

        for event in events:
            ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
            d = event.data

            if event.event_type == EventType.CYCLE_START:
                activity.write(f"[bold cyan]\\[{ts}][/] Cycle {d.get('cycle', '?')} started")
            elif event.event_type == EventType.CYCLE_END:
                activity.write(
                    f"[bold cyan]\\[{ts}][/] Cycle {d.get('cycle', '?')} complete: "
                    f"{d.get('markets', 0)} markets, "
                    f"{d.get('signals', 0)} signals, "
                    f"{d.get('fills', 0)} fills"
                )
            elif event.event_type == EventType.CYCLE_ERROR:
                activity.write(f"[bold red]\\[{ts}] ERROR:[/] {d.get('error', '?')}")
            elif event.event_type == EventType.MARKETS_FETCHED:
                activity.write(
                    f"[dim]\\[{ts}][/] Fetched {d.get('total', 0)} markets, "
                    f"{d.get('selected', 0)} selected"
                )
            elif event.event_type == EventType.SIGNAL_GENERATED:
                side = d.get("side", "?").upper()
                activity.write(
                    f"[bold yellow]\\[{ts}] SIGNAL[/] {side} "
                    f"{d.get('slug', '?')[:25]} @ {d.get('price', '?')} "
                    f"x {d.get('quantity', '?')}"
                )
            elif event.event_type == EventType.ORDER_FILLED:
                activity.write(
                    f"[bold green]\\[{ts}] FILLED[/] {d.get('side', '?').upper()} "
                    f"{d.get('slug', '?')[:25]}: "
                    f"{d.get('quantity', '?')} contracts, ${d.get('total_cost', '?')}"
                )
            elif event.event_type == EventType.ORDER_REJECTED:
                activity.write(
                    f"[bold red]\\[{ts}] REJECTED[/] {d.get('slug', '?')[:25]}: "
                    f"{d.get('reason', '?')}"
                )
            elif event.event_type == EventType.EXIT_SIGNAL:
                activity.write(
                    f"[bold magenta]\\[{ts}] EXIT[/] {d.get('side', '?').upper()} "
                    f"{d.get('token_id', '?')[:20]} reason={d.get('reason', '?')} "
                    f"pnl={d.get('pnl_per_contract', '?')}"
                )
            elif event.event_type == EventType.POSITION_CLOSED:
                activity.write(
                    f"[bold green]\\[{ts}] CLOSED[/] {d.get('side', '?').upper()} "
                    f"{d.get('token_id', '?')[:20]}: "
                    f"{d.get('quantity', '?')} contracts @ {d.get('price', '?')}"
                )
            elif event.event_type == EventType.MARKET_SCANNED:
                slug = d.get("slug", "?")
                self._market_prices[slug] = (
                    d.get("yes_price", "0"),
                    d.get("no_price", "0"),
                )

        if events:
            scanned = [
                e for e in events if e.event_type == EventType.MARKET_SCANNED
            ]
            if scanned:
                scan_table.clear()
                for e in scanned:
                    d = e.data
                    scan_table.add_row(
                        d.get("slug", "?")[:25],
                        d.get("yes_price", "--"),
                        d.get("no_price", "--"),
                        d.get("signal") or "--",
                    )

        self._refresh_header()
        self._refresh_positions()

    def _refresh_header(self) -> None:
        if self._portfolio is None:
            return
        header_bar = self.query_one("#header-bar", HeaderBar)
        header_bar.update_stats(
            balance=self._portfolio.balance,
            initial_balance=self._portfolio.initial_balance,
            realized_pnl=self._portfolio.realized_pnl,
            cycle=self._cycle_number,
            start_time=self._start_time,
        )

    def _refresh_positions(self) -> None:
        if self._portfolio is None:
            return
        pos_table = self.query_one("#positions", DataTable)
        pos_table.clear()
        for (token_id, side), pos in self._portfolio.positions.items():
            short_id = token_id[:12] + "..." if len(token_id) > 15 else token_id
            # Try to estimate unrealized P&L from cached prices
            unrl_str = "--"
            for slug, prices in self._market_prices.items():
                if side == Side.YES:
                    try:
                        current = Decimal(prices[0])
                        unrealized = (current - pos.avg_price) * pos.quantity
                        unrl_str = f"{'+' if unrealized >= 0 else ''}{unrealized:.2f}"
                    except Exception:
                        pass
                    break

            pos_table.add_row(
                short_id,
                side.value.upper(),
                str(pos.quantity),
                f"{pos.avg_price:.4f}",
                unrl_str,
            )

    def action_toggle_pause(self) -> None:
        if self._paused.is_set():
            self._paused.clear()
            activity = self.query_one("#activity", RichLog)
            activity.write("[bold yellow]--- PAUSED ---[/]")
        else:
            self._paused.set()
            activity = self.query_one("#activity", RichLog)
            activity.write("[bold green]--- RESUMED ---[/]")
