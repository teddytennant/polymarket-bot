"""JSON save/load for portfolio state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from polymarket_bot.portfolio import Portfolio


def save_state(portfolio: Portfolio, path: Path) -> None:
    """Atomically write portfolio state to disk.

    Writes to a temporary file first, then renames to the target path.
    This prevents state corruption if the process crashes mid-write.
    """
    data = portfolio.to_dict()
    content = json.dumps(data, indent=2) + "\n"

    # Write to temp file in the same directory, then atomically rename
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode())
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_path, str(path))
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_state(path: Path) -> Optional[Portfolio]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Portfolio.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        return None
