"""Thread-safe event bus for communication between worker and UI threads."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    CYCLE_START = "cycle_start"
    CYCLE_END = "cycle_end"
    CYCLE_ERROR = "cycle_error"
    MARKETS_FETCHED = "markets_fetched"
    SIGNAL_GENERATED = "signal_generated"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    MARKET_SETTLED = "market_settled"
    MARKET_SCANNED = "market_scanned"
    EXIT_SIGNAL = "exit_signal"
    POSITION_CLOSED = "position_closed"


@dataclass(frozen=True)
class Event:
    event_type: EventType
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Thread-safe event bus with cursor-based draining.

    The worker thread calls emit() to publish events.
    The UI thread calls drain_from(cursor) to consume new events.
    Cursors are monotonic and survive trimming.
    """

    def __init__(self, max_events: int = 1000):
        self._lock = threading.Lock()
        self._events: list[Event] = []
        self._base_offset: int = 0
        self._max_events = max_events

    def emit(self, event_type: EventType, **data: Any) -> None:
        event = Event(event_type=event_type, timestamp=time.time(), data=data)
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                trim = len(self._events) - self._max_events
                self._events = self._events[trim:]
                self._base_offset += trim

    def drain_from(self, cursor: int) -> tuple[list[Event], int]:
        """Return events after cursor and the new cursor position."""
        with self._lock:
            start = cursor - self._base_offset
            if start < 0:
                start = 0
            events = list(self._events[start:])
            new_cursor = self._base_offset + len(self._events)
            return events, new_cursor

    @property
    def total_events(self) -> int:
        with self._lock:
            return self._base_offset + len(self._events)
