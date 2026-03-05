"""JSON save/load for portfolio state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from polymarket_bot.portfolio import Portfolio


def save_state(portfolio: Portfolio, path: Path) -> None:
    data = portfolio.to_dict()
    path.write_text(json.dumps(data, indent=2) + "\n")


def load_state(path: Path) -> Optional[Portfolio]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Portfolio.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        return None
