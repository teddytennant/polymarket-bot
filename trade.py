#!/usr/bin/env python3
"""12-hour trading session. Finds edge-based positions, monitors for settlements, sells at end."""

import time
from decimal import Decimal
from pathlib import Path

from polymarket_bot.client import PolymarketClient
from polymarket_bot.engine import PaperTradingEngine
from polymarket_bot.models import Order, OrderStatus, OrderType, Side
from polymarket_bot.persistence import load_state, save_state
from polymarket_bot.portfolio import Portfolio

STATE_FILE = Path("sim_state.json")
DURATION_HOURS = 12


def buy(engine, portfolio, token_id, side, price, quantity, label=""):
    order = Order(
        token_id=token_id, side=side, order_type=OrderType.LIMIT,
        price=price, quantity=quantity, status=OrderStatus.PENDING,
    )
    try:
        fills = engine.submit_order(order)
        if fills:
            total = sum(f.total_cost for f in fills)
            qty = sum(f.quantity for f in fills)
            avg = total / qty if qty else price
            print(f"  BUY {label or token_id[:20]} {side.value.upper()}: {qty} @ {avg:.4f} = ${total:.2f}")
            return qty, total
    except ValueError as e:
        print(f"  REJECTED {label}: {e}")
    return 0, Decimal("0")


def sell_all(client, engine, portfolio):
    """Sell every open position."""
    total_proceeds = Decimal("0")
    for (token_id, side), pos in list(portfolio.positions.items()):
        short_id = token_id[:15]
        try:
            fills = engine.sell_position(token_id, side, pos.quantity)
            if fills:
                total = sum(f.total_cost for f in fills)
                qty = sum(f.quantity for f in fills)
                avg = total / qty if qty else Decimal("0")
                pnl = total - pos.avg_price * qty
                total_proceeds += total
                print(f"  SOLD {short_id:>15} {side.value.upper()}: {qty:>5} @ {avg:.4f} = ${total:>8.2f}  (P&L: {pnl:+.2f})")
            else:
                print(f"  NO BIDS {short_id}: empty orderbook")
        except ValueError as e:
            print(f"  ERROR {short_id}: {e}")
    return total_proceeds


def check_settlements(client, engine, portfolio, token_market_map):
    """Check all held tokens for settlements. Returns count settled."""
    settled = 0
    for token_id, condition_id in token_market_map.items():
        try:
            market = client.get_market(condition_id)
            if not market.closed:
                continue

            if len(market.outcome_prices) < 2:
                continue

            if market.outcome_prices[0] >= Decimal("0.99"):
                winning_side = "yes"
            elif market.outcome_prices[1] >= Decimal("0.99"):
                winning_side = "no"
            else:
                continue

            for side in (Side.YES, Side.NO):
                pos = portfolio.get_position(token_id, side)
                if pos:
                    won = side.value == winning_side
                    settle_price = Decimal("1.00") if won else Decimal("0.00")
                    pnl = (settle_price - pos.avg_price) * pos.quantity
                    short_id = token_id[:15]
                    print(f"  SETTLED {short_id} {side.value.upper()}: {'WON' if won else 'LOST'} "
                          f"{pos.quantity} contracts, P&L: {pnl:+.2f}")

            portfolio.settle_market(token_id, winning_side=winning_side)
            settled += 1
        except Exception as e:
            print(f"  WARNING: settlement check failed for {token_id[:15]}: {e}")
    return settled


def find_edge_markets(client):
    """Find markets where ask < recent price mean (positive edge)."""
    opportunities = []

    try:
        markets = client.get_markets(limit=100, active=True, order="volume_24hr")
    except Exception as e:
        print(f"  WARNING: market fetch failed: {e}")
        return []

    for m in markets:
        if not m.active or m.closed:
            continue
        if not m.yes_token_id or not m.no_token_id:
            continue

        try:
            yes_ob = client.get_orderbook(m.yes_token_id)
            no_ob = client.get_orderbook(m.no_token_id)

            yes_ask = yes_ob.best_ask
            yes_bid = yes_ob.best_bid
            if not yes_ask or not yes_bid:
                continue

            spread = yes_ask - yes_bid
            if spread > Decimal("0.03") or spread <= 0:
                continue

            history = client.get_price_history(m.yes_token_id, interval="1d", fidelity=60)
            if len(history) < 5:
                continue

            prices = [p.price for p in history[:10]]
            mean = sum(prices) / len(prices)

            # YES edge
            edge = mean - yes_ask
            if edge > Decimal("0"):
                opportunities.append({
                    "condition_id": m.condition_id,
                    "token_id": m.yes_token_id,
                    "side": Side.YES,
                    "ask": yes_ask,
                    "bid": yes_bid,
                    "mean": mean,
                    "edge": edge,
                    "spread": spread,
                    "volume": m.volume,
                    "question": m.question[:60],
                    "slug": m.slug,
                })

            # NO edge
            no_ask = no_ob.best_ask
            no_bid = no_ob.best_bid
            if no_ask and no_bid:
                no_mean = Decimal("1.00") - mean
                no_edge = no_mean - no_ask
                if no_edge > Decimal("0"):
                    opportunities.append({
                        "condition_id": m.condition_id,
                        "token_id": m.no_token_id,
                        "side": Side.NO,
                        "ask": no_ask,
                        "bid": no_bid,
                        "mean": no_mean,
                        "edge": no_edge,
                        "spread": no_ask - no_bid if no_ask > no_bid else Decimal("0"),
                        "volume": m.volume,
                        "question": m.question[:60],
                        "slug": m.slug,
                    })

            time.sleep(0.3)
        except Exception as e:
            if "429" in str(e):
                print(f"  Rate limited, waiting...")
                time.sleep(3)
            else:
                print(f"  WARNING: failed for {m.slug[:30]}: {e}")

    opportunities.sort(key=lambda o: o["edge"], reverse=True)
    return opportunities


def print_status(portfolio, label=""):
    invested = sum(pos.avg_price * pos.quantity for pos in portfolio.positions.values())
    total = portfolio.balance + invested
    ret = (total - portfolio.initial_balance) / portfolio.initial_balance * 100
    print(f"  {label}Balance: ${portfolio.balance:.2f} | Invested: ${invested:.2f} | "
          f"Total: ${total:.2f} | P&L: ${portfolio.realized_pnl:.2f} | Return: {ret:+.2f}%")


def run():
    client = PolymarketClient()
    portfolio = load_state(STATE_FILE)
    if portfolio is None:
        portfolio = Portfolio(initial_balance=Decimal("10000"))
    engine = PaperTradingEngine(portfolio=portfolio, client=client)

    end_time = time.time() + DURATION_HOURS * 3600
    start_time = time.time()

    # Build token->market map for settlement checks
    token_market_map: dict[str, str] = {}

    print("=" * 60)
    print(f"  12-HOUR TRADING SESSION")
    print(f"  Start: {time.strftime('%H:%M:%S')}")
    print(f"  End:   {time.strftime('%H:%M:%S', time.localtime(end_time))}")
    print("=" * 60)
    print_status(portfolio, "START: ")
    print()

    # PHASE 1: Initial position building
    print("=" * 60)
    print("PHASE 1: BUILDING POSITIONS")
    print("=" * 60)

    print("\n--- Scanning for edge-based opportunities ---")
    opportunities = find_edge_markets(client)
    print(f"  Found {len(opportunities)} markets with positive edge")
    trades_placed = 0
    for opp in opportunities:
        if trades_placed >= 12:
            break
        token_id = opp["token_id"]
        side = opp["side"]
        if portfolio.get_position(token_id, side):
            continue
        if opp["edge"] <= opp["spread"]:
            continue
        budget = min(Decimal("500"), portfolio.balance * Decimal("0.06"))
        qty = min(500, int(budget / opp["ask"]))
        if qty >= 20:
            print(f"  {opp['question']}")
            print(f"    edge={opp['edge']:.4f} spread={opp['spread']} vol={opp['volume']:.0f}")
            bought, _ = buy(engine, portfolio, token_id, side, opp["ask"], qty,
                            opp["slug"][:20])
            if bought > 0:
                trades_placed += 1
                token_market_map[token_id] = opp["condition_id"]
            time.sleep(0.3)

    save_state(portfolio, STATE_FILE)

    print()
    print_status(portfolio, "AFTER BUYS: ")
    print(f"  Positions: {len(portfolio.positions)}")
    for (token_id, side), pos in portfolio.positions.items():
        short_id = token_id[:15]
        inv = pos.avg_price * pos.quantity
        potential = (Decimal("1.00") - pos.avg_price) * pos.quantity
        print(f"    {short_id:>15} {side.value.upper()}: {pos.quantity:>5} @ {pos.avg_price:.4f} "
              f"= ${inv:.2f}  (win: +${potential:.2f})")

    # PHASE 2: Monitor
    print()
    print("=" * 60)
    print("PHASE 2: MONITORING (12 hours)")
    print("=" * 60)

    cycle = 0
    last_full_print = 0

    while time.time() < end_time:
        cycle += 1
        elapsed_min = (time.time() - start_time) / 60
        elapsed_hr = elapsed_min / 60

        settled = check_settlements(client, engine, portfolio, token_market_map)
        if settled > 0:
            save_state(portfolio, STATE_FILE)
            print_status(portfolio, f"  [{elapsed_hr:.1f}h] ")

        # Every 30 min: take-profit checks
        if cycle % 6 == 0 and portfolio.balance > Decimal("200"):
            for (token_id, side), pos in list(portfolio.positions.items()):
                try:
                    ob = client.get_orderbook(token_id)
                    bid = ob.best_bid
                    if bid and bid >= pos.avg_price + Decimal("0.03"):
                        fills = engine.sell_position(token_id, side, pos.quantity)
                        if fills:
                            total = sum(f.total_cost for f in fills)
                            qty = sum(f.quantity for f in fills)
                            pnl = total - pos.avg_price * qty
                            short_id = token_id[:15]
                            print(f"  [{elapsed_hr:.1f}h] TAKE PROFIT {short_id}: "
                                  f"{qty} contracts, P&L: {pnl:+.2f}")
                            save_state(portfolio, STATE_FILE)
                except Exception as e:
                    print(f"  WARNING: take-profit check failed: {e}")

        # Every hour: new edges
        if cycle % 12 == 0 and portfolio.balance > Decimal("500"):
            try:
                new_opps = find_edge_markets(client)
                for opp in new_opps[:3]:
                    token_id = opp["token_id"]
                    side = opp["side"]
                    if portfolio.get_position(token_id, side):
                        continue
                    if opp["edge"] <= opp["spread"]:
                        continue
                    budget = min(Decimal("400"), portfolio.balance * Decimal("0.05"))
                    qty = min(300, int(budget / opp["ask"]))
                    if qty >= 20:
                        bought, _ = buy(engine, portfolio, token_id, side, opp["ask"], qty,
                                        opp["slug"][:20])
                        if bought:
                            token_market_map[token_id] = opp["condition_id"]
                            save_state(portfolio, STATE_FILE)
                            break
            except Exception as e:
                print(f"  WARNING: edge scan failed: {e}")

        # Print status every hour
        if elapsed_min - last_full_print >= 60:
            last_full_print = elapsed_min
            print()
            print_status(portfolio, f"  [{elapsed_hr:.1f}h] ")
            for (token_id, side), pos in portfolio.positions.items():
                try:
                    ob = client.get_orderbook(token_id)
                    bid = ob.best_bid
                    if bid:
                        pnl_per = bid - pos.avg_price
                        short_id = token_id[:15]
                        print(f"    {short_id:>15}: bid={bid} pnl/c={pnl_per:+.4f} "
                              f"qty={pos.quantity}")
                except Exception as e:
                    print(f"  WARNING: status check failed: {e}")

        save_state(portfolio, STATE_FILE)

        sleep_time = min(300, max(0, end_time - time.time()))
        if sleep_time > 0:
            time.sleep(sleep_time)

    # PHASE 3: Liquidation
    print()
    print("=" * 60)
    print("PHASE 3: FINAL LIQUIDATION")
    print("=" * 60)

    print("\n--- Final settlement check ---")
    check_settlements(client, engine, portfolio, token_market_map)
    save_state(portfolio, STATE_FILE)

    if portfolio.positions:
        print("\n--- Selling all remaining positions ---")
        sell_all(client, engine, portfolio)
        save_state(portfolio, STATE_FILE)

    print()
    print("=" * 60)
    print("  SESSION COMPLETE")
    print("=" * 60)
    ret = (portfolio.balance - portfolio.initial_balance) / portfolio.initial_balance * 100
    print(f"  Final Balance:   ${portfolio.balance:.2f}")
    print(f"  Initial Balance: ${portfolio.initial_balance:.2f}")
    print(f"  Realized P&L:    ${portfolio.realized_pnl:.2f}")
    print(f"  Return:          {ret:+.2f}%")
    print("=" * 60)
    save_state(portfolio, STATE_FILE)


if __name__ == "__main__":
    run()
