"""CLI entry point (argparse, main polling loop)."""

from __future__ import annotations

import argparse
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional

from polymarket_bot.client import PolymarketClient
from polymarket_bot.engine import PaperTradingEngine
from polymarket_bot.events import Event, EventBus, EventType
from polymarket_bot.models import Order, OrderStatus, Side
from polymarket_bot.persistence import load_state, save_state
from polymarket_bot.portfolio import Portfolio
from polymarket_bot.strategy import MeanReversionStrategy, Strategy, TradeSignal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polymarket-bot",
        description="Paper trading bot for Polymarket prediction markets",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the paper trading loop")
    run_parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds")
    run_parser.add_argument("--balance", type=int, default=10000, help="Initial balance in dollars")
    run_parser.add_argument("--state-file", type=str, default="state.json", help="State file path")
    run_parser.add_argument("--cycles", type=int, default=0, help="Run N cycles then exit (0=infinite)")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Show all events including market scans")
    run_parser.add_argument("--threshold", type=float, default=0.05, help="Mean reversion threshold (default: 0.05)")
    run_parser.add_argument("--quantity", type=int, default=10, help="Contracts per trade (default: 10)")
    run_parser.add_argument("--window", type=int, default=10, help="Price history window (default: 10)")
    run_parser.add_argument("--min-volume", type=int, default=0, help="Min market volume filter")
    run_parser.add_argument("--take-profit", type=float, default=0, help="Sell when per-contract gain >= threshold (0=disabled)")
    run_parser.add_argument("--stop-loss", type=float, default=0, help="Sell when per-contract loss >= threshold (0=disabled)")

    status_parser = subparsers.add_parser("status", help="Show portfolio status")
    status_parser.add_argument("--state-file", type=str, default="state.json", help="State file path")

    markets_parser = subparsers.add_parser("markets", help="List available markets")
    markets_parser.add_argument("--active", action="store_true", default=True, help="Show active markets only")
    markets_parser.add_argument("--limit", type=int, default=20, help="Max markets to show")

    dash_parser = subparsers.add_parser("dashboard", help="Launch TUI dashboard")
    dash_parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds")
    dash_parser.add_argument("--balance", type=int, default=10000, help="Initial balance in dollars")
    dash_parser.add_argument("--state-file", type=str, default="state.json", help="State file path")
    dash_parser.add_argument("--threshold", type=float, default=0.05, help="Mean reversion threshold (default: 0.05)")
    dash_parser.add_argument("--quantity", type=int, default=10, help="Contracts per trade (default: 10)")
    dash_parser.add_argument("--window", type=int, default=10, help="Price history window (default: 10)")
    dash_parser.add_argument("--min-volume", type=int, default=0, help="Min market volume filter")
    dash_parser.add_argument("--take-profit", type=float, default=0, help="Sell when per-contract gain >= threshold (0=disabled)")
    dash_parser.add_argument("--stop-loss", type=float, default=0, help="Sell when per-contract loss >= threshold (0=disabled)")

    return parser


def cmd_markets(client: PolymarketClient, active: bool, limit: int) -> None:
    markets = client.get_markets(limit=limit, active=active if active else None)
    if not markets:
        print("No markets found.")
        return
    print(f"{'Slug':<40} {'Yes':>6} {'No':>6} {'Volume':>10}  Question")
    print("-" * 100)
    for m in markets:
        print(f"{m.slug[:40]:<40} {m.yes_price:>6.2f} {m.no_price:>6.2f} {m.volume:>10.0f}  {m.question[:40]}")


def cmd_status(state_file: str) -> None:
    portfolio = load_state(Path(state_file))
    if portfolio is None:
        print(f"No state file found at {state_file}")
        return
    print(f"Balance:      ${portfolio.balance:.2f}")
    print(f"Initial:      ${portfolio.initial_balance:.2f}")
    print(f"Realized P&L: ${portfolio.realized_pnl:.2f}")
    ret = (
        (portfolio.balance - portfolio.initial_balance)
        / portfolio.initial_balance
        * 100
        if portfolio.initial_balance
        else Decimal("0")
    )
    print(f"Return:       {'+' if ret >= 0 else ''}{ret:.2f}%")
    positions = portfolio.positions
    if positions:
        print(f"\nPositions ({len(positions)}):")
        print(f"  {'Token ID':<25} {'Side':>4} {'Qty':>5} {'Avg Price':>10}")
        print(f"  {'-'*25} {'-'*4} {'-'*5} {'-'*10}")
        for (token_id, side), pos in positions.items():
            short_id = token_id[:12] + "..." if len(token_id) > 15 else token_id
            print(f"  {short_id:<25} {side.value.upper():>4} {pos.quantity:>5} {pos.avg_price:>10.4f}")
    else:
        print("\nNo open positions.")


def format_event(event: Event, verbose: bool = False) -> Optional[str]:
    ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
    d = event.data
    et = event.event_type

    if et == EventType.CYCLE_START:
        return f"[{ts}] --- Cycle {d.get('cycle', '?')} started ---"

    if et == EventType.CYCLE_END:
        exits = d.get("exits", 0)
        exits_str = f", {exits} exits" if exits else ""
        return (
            f"[{ts}] Cycle {d.get('cycle', '?')} complete: "
            f"{d.get('markets', 0)} markets scanned, "
            f"{d.get('signals', 0)} signals, "
            f"{d.get('fills', 0)} fills"
            f"{exits_str}"
        )

    if et == EventType.CYCLE_ERROR:
        return f"[{ts}] ERROR: {d.get('error', '?')}"

    if et == EventType.MARKETS_FETCHED:
        return (
            f"[{ts}] Fetched {d.get('total', 0)} markets, "
            f"{d.get('selected', 0)} selected by strategy"
        )

    if et == EventType.SIGNAL_GENERATED:
        side = d.get("side", "?").upper()
        return (
            f"[{ts}] SIGNAL {side} {d.get('slug', d.get('token_id', '?'))[:30]} "
            f"@ {d.get('price', '?')} x {d.get('quantity', '?')}"
        )

    if et == EventType.ORDER_FILLED:
        side = d.get("side", "?").upper()
        return (
            f"[{ts}] FILLED {side} {d.get('slug', d.get('token_id', '?'))[:30]}: "
            f"{d.get('quantity', '?')} contracts, cost ${d.get('total_cost', '?')}"
        )

    if et == EventType.ORDER_REJECTED:
        return (
            f"[{ts}] REJECTED {d.get('slug', d.get('token_id', '?'))[:30]}: "
            f"{d.get('reason', '?')}"
        )

    if et == EventType.EXIT_SIGNAL:
        side = d.get("side", "?").upper()
        return (
            f"[{ts}] EXIT {side} {d.get('slug', d.get('token_id', '?'))[:30]} "
            f"reason={d.get('reason', '?')} "
            f"pnl_per_contract={d.get('pnl_per_contract', '?')}"
        )

    if et == EventType.POSITION_CLOSED:
        side = d.get("side", "?").upper()
        return (
            f"[{ts}] CLOSED {side} {d.get('slug', d.get('token_id', '?'))[:30]}: "
            f"{d.get('quantity', '?')} contracts @ {d.get('price', '?')}"
        )

    if et == EventType.MARKET_SCANNED and verbose:
        signal = d.get("signal")
        signal_str = f" -> {signal}" if signal else ""
        return (
            f"[{ts}]   scan {d.get('slug', '?')[:30]:<30} "
            f"yes={d.get('yes_price', '--'):>6} no={d.get('no_price', '--'):>6}"
            f"{signal_str}"
        )

    return None


def print_portfolio_summary(portfolio: Portfolio) -> None:
    ret = (
        (portfolio.balance - portfolio.initial_balance)
        / portfolio.initial_balance
        * 100
        if portfolio.initial_balance
        else Decimal("0")
    )
    pnl_sign = "+" if portfolio.realized_pnl >= 0 else ""
    ret_sign = "+" if ret >= 0 else ""
    n_pos = len(portfolio.positions)
    print(
        f"         Balance: ${portfolio.balance:.2f} | "
        f"P&L: {pnl_sign}${portfolio.realized_pnl:.2f} | "
        f"Return: {ret_sign}{ret:.2f}% | "
        f"Positions: {n_pos}"
    )


def run_cycle(
    client: PolymarketClient,
    portfolio: Portfolio,
    strategy: Strategy,
    event_bus: Optional[EventBus] = None,
    cycle_number: int = 0,
    take_profit: Decimal = Decimal("0"),
    stop_loss: Decimal = Decimal("0"),
) -> None:
    if event_bus:
        event_bus.emit(EventType.CYCLE_START, cycle=cycle_number)

    markets = client.get_markets(limit=100, active=True)
    selected = strategy.select_markets(markets)

    if event_bus:
        event_bus.emit(
            EventType.MARKETS_FETCHED,
            cycle=cycle_number,
            total=len(markets),
            selected=len(selected),
        )

    engine = PaperTradingEngine(portfolio=portfolio, client=client)

    signals_count = 0
    fills_count = 0

    for market in selected:
        if not market.yes_token_id or not market.no_token_id:
            continue

        yes_orderbook = client.get_orderbook(market.yes_token_id)
        no_orderbook = client.get_orderbook(market.no_token_id)
        price_history = client.get_price_history(market.yes_token_id)
        signal = strategy.evaluate(market, yes_orderbook, no_orderbook, price_history, portfolio)

        if event_bus:
            event_bus.emit(
                EventType.MARKET_SCANNED,
                slug=market.slug,
                yes_price=str(market.yes_price),
                no_price=str(market.no_price),
                yes_token_id=market.yes_token_id,
                no_token_id=market.no_token_id,
                signal=signal.side.value.upper() if signal else None,
            )

        if signal is not None:
            signals_count += 1
            if event_bus:
                event_bus.emit(
                    EventType.SIGNAL_GENERATED,
                    slug=market.slug,
                    token_id=signal.token_id,
                    side=signal.side.value,
                    price=str(signal.price),
                    quantity=signal.quantity,
                )

            order = Order(
                token_id=signal.token_id,
                side=signal.side,
                order_type=signal.order_type,
                price=signal.price,
                quantity=signal.quantity,
                status=OrderStatus.PENDING,
            )
            try:
                fills = engine.submit_order(order)
                if fills:
                    total = sum(f.total_cost for f in fills)
                    qty = sum(f.quantity for f in fills)
                    fills_count += len(fills)
                    if event_bus:
                        event_bus.emit(
                            EventType.ORDER_FILLED,
                            slug=market.slug,
                            token_id=signal.token_id,
                            side=signal.side.value,
                            quantity=qty,
                            total_cost=str(total),
                        )
                    else:
                        print(f"  Filled {signal.side.value.upper()} {market.slug}: "
                              f"{qty} contracts, cost {total}")
            except ValueError as e:
                if event_bus:
                    event_bus.emit(
                        EventType.ORDER_REJECTED,
                        slug=market.slug,
                        token_id=signal.token_id,
                        reason=str(e),
                    )
                else:
                    print(f"  Order rejected: {e}")

    # Exit monitoring: check positions for take-profit / stop-loss
    exits_count = 0
    if take_profit > 0 or stop_loss > 0:
        positions_snapshot = list(portfolio.positions.items())
        for (token_id, side), pos in positions_snapshot:
            orderbook = client.get_orderbook(token_id)
            current_bid = orderbook.best_bid
            if current_bid is None:
                continue

            per_contract_pnl = current_bid - pos.avg_price

            reason = None
            if take_profit > 0 and per_contract_pnl >= take_profit:
                reason = "take_profit"
            elif stop_loss > 0 and per_contract_pnl <= -stop_loss:
                reason = "stop_loss"

            if reason is None:
                continue

            if event_bus:
                event_bus.emit(
                    EventType.EXIT_SIGNAL,
                    token_id=token_id,
                    side=side.value,
                    reason=reason,
                    pnl_per_contract=str(per_contract_pnl),
                )

            try:
                sell_fills = engine.sell_position(token_id, side, pos.quantity)
                if sell_fills:
                    exits_count += 1
                    total = sum(f.total_cost for f in sell_fills)
                    qty = sum(f.quantity for f in sell_fills)
                    if event_bus:
                        event_bus.emit(
                            EventType.POSITION_CLOSED,
                            token_id=token_id,
                            side=side.value,
                            quantity=qty,
                            price=str(total / qty) if qty else "0",
                            reason=reason,
                        )
                    else:
                        print(f"  Closed {side.value.upper()} {token_id[:20]}: "
                              f"{qty} contracts ({reason})")
            except ValueError as e:
                if event_bus:
                    event_bus.emit(
                        EventType.ORDER_REJECTED,
                        token_id=token_id,
                        reason=str(e),
                    )
                else:
                    print(f"  Exit sell failed for {token_id[:20]}: {e}")

    if event_bus:
        event_bus.emit(
            EventType.CYCLE_END,
            cycle=cycle_number,
            markets=len(selected),
            signals=signals_count,
            fills=fills_count,
            exits=exits_count,
        )


def cmd_run(
    client: PolymarketClient,
    state_path: Path,
    portfolio: Portfolio,
    strategy: Strategy,
    interval: int,
    max_cycles: int = 0,
    verbose: bool = False,
    take_profit: Decimal = Decimal("0"),
    stop_loss: Decimal = Decimal("0"),
) -> None:
    event_bus = EventBus()
    cursor = 0
    cycle = 0

    print(f"Running paper trading loop (interval={interval}s, "
          f"cycles={'infinite' if max_cycles == 0 else max_cycles})...")
    print_portfolio_summary(portfolio)
    print()

    try:
        while max_cycles == 0 or cycle < max_cycles:
            cycle += 1
            try:
                run_cycle(
                    client, portfolio, strategy,
                    event_bus=event_bus, cycle_number=cycle,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                )
                save_state(portfolio, state_path)
            except Exception as e:
                event_bus.emit(EventType.CYCLE_ERROR, cycle=cycle, error=str(e))

            events, cursor = event_bus.drain_from(cursor)
            for event in events:
                line = format_event(event, verbose=verbose)
                if line is not None:
                    print(line)

            print_portfolio_summary(portfolio)
            print()

            if max_cycles == 0 or cycle < max_cycles:
                time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopping...")

    save_state(portfolio, state_path)
    print(f"State saved to {state_path}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "markets":
        client = PolymarketClient()
        cmd_markets(client, active=args.active, limit=args.limit)
    elif args.command == "status":
        cmd_status(args.state_file)
    elif args.command == "run":
        client = PolymarketClient()
        state_path = Path(args.state_file)
        portfolio = load_state(state_path)
        if portfolio is None:
            portfolio = Portfolio(initial_balance=Decimal(args.balance))
            print(f"Starting new portfolio with balance: ${portfolio.balance:.2f}")
        else:
            print(f"Loaded portfolio: balance=${portfolio.balance:.2f}, "
                  f"positions={len(portfolio.positions)}")

        strategy = MeanReversionStrategy(
            window=args.window,
            threshold=Decimal(str(args.threshold)),
            order_quantity=args.quantity,
            min_volume=args.min_volume,
        )

        cmd_run(
            client=client,
            state_path=state_path,
            portfolio=portfolio,
            strategy=strategy,
            interval=args.interval,
            max_cycles=args.cycles,
            verbose=args.verbose,
            take_profit=Decimal(str(args.take_profit)),
            stop_loss=Decimal(str(args.stop_loss)),
        )
    elif args.command == "dashboard":
        from polymarket_bot.tui import DashboardApp

        app = DashboardApp(
            interval=args.interval,
            balance=args.balance,
            state_file=args.state_file,
            threshold=Decimal(str(args.threshold)),
            order_quantity=args.quantity,
            window=args.window,
            min_volume=args.min_volume,
            take_profit=Decimal(str(args.take_profit)),
            stop_loss=Decimal(str(args.stop_loss)),
        )
        app.run()


if __name__ == "__main__":
    main()
