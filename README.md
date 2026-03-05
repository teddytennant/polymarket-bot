# polymarket-bot

Paper trading bot for [Polymarket](https://polymarket.com) prediction markets. Scans live markets via the Gamma and CLOB APIs, evaluates a mean-reversion strategy against real orderbook data, and simulates trades with a virtual portfolio.

## Features

- **Paper trading** against real CLOB orderbook levels
- **Mean reversion strategy** with configurable threshold, window, and position sizing
- **CLI interface** with `run`, `status`, `markets`, and `dashboard` commands
- **TUI dashboard** (Textual) with live P&L, positions table, market scanner, and activity log
- **Standalone 12-hour trading session** script with edge-based entry, take-profit, and liquidation phases
- **Persistent state** via JSON (survives restarts)
- **Decimal precision** throughout (no floating-point price math)

## Quick Start

```bash
# Enter dev shell (requires Nix with flakes)
nix develop

# List top markets by 24h volume
polymarket-bot markets

# Start paper trading (polls every 60s)
polymarket-bot run --interval 60 --balance 10000

# Check portfolio
polymarket-bot status

# Launch TUI dashboard
polymarket-bot dashboard
```

## CLI Options

```
polymarket-bot run [OPTIONS]
  --interval SECONDS    Polling interval (default: 60)
  --balance DOLLARS     Initial virtual balance (default: 10000)
  --threshold FLOAT     Mean reversion threshold (default: 0.05)
  --quantity INT        Contracts per trade (default: 10)
  --window INT          Price history lookback window (default: 10)
  --min-volume INT      Minimum market volume filter (default: 0)
  --take-profit FLOAT   Exit when per-contract gain >= threshold (0=disabled)
  --stop-loss FLOAT     Exit when per-contract loss >= threshold (0=disabled)
  --cycles INT          Max cycles then exit (0=infinite)
  --state-file PATH     Portfolio state file (default: state.json)
  -v, --verbose         Show all market scan events
```

## 12-Hour Trading Session

```bash
python trade.py
```

Three-phase autonomous session:
1. **Build positions** - scans top markets for edge (ask < recent price mean), buys up to 12 positions
2. **Monitor** - checks settlements, takes profit at +3c, scans for new edges hourly
3. **Liquidate** - sells all remaining positions, prints final P&L

## Architecture

```
src/polymarket_bot/
├── models.py       # Frozen dataclasses (Market, Orderbook, Order, Fill, Position)
├── client.py       # Gamma API (market discovery) + CLOB API (orderbook, pricing)
├── portfolio.py    # Virtual balance, position tracking, P&L calculation
├── engine.py       # Paper trading: matches orders against real CLOB levels
├── strategy.py     # Strategy ABC + MeanReversionStrategy
├── events.py       # Thread-safe event bus (worker <-> UI)
├── persistence.py  # JSON state save/load
├── runner.py       # CLI entry point (argparse, polling loop)
└── tui.py          # Textual TUI dashboard
```

### How It Works

Polymarket markets have **Yes** and **No** outcome tokens, each with its own CLOB orderbook. Prices are decimals between 0 and 1, representing implied probability. Winning tokens pay $1.00; losing tokens pay $0.

The bot fetches markets from the Gamma API, pulls orderbooks from the CLOB API, and evaluates a mean-reversion strategy:

- **Buy YES** if the current ask is significantly below the recent price average
- **Buy NO** if the YES price is significantly above the average (meaning NO is cheap)

Orders are simulated against real orderbook levels — market orders walk all available ask levels, limit orders stop at the threshold price.

### APIs Used (all public, no auth required)

| API | Base URL | Purpose |
|-----|----------|---------|
| Gamma | `gamma-api.polymarket.com` | Market discovery, metadata |
| CLOB | `clob.polymarket.com` | Orderbooks, pricing, price history |

## Development

```bash
nix develop
pytest                    # run tests
pytest --cov=polymarket_bot  # with coverage
```

## License

MIT
