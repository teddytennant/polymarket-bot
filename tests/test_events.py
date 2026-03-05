"""Tests for EventBus."""

import threading

import pytest

from polymarket_bot.events import Event, EventBus, EventType


class TestEventType:
    def test_all_event_types_exist(self):
        assert EventType.CYCLE_START.value == "cycle_start"
        assert EventType.CYCLE_END.value == "cycle_end"
        assert EventType.CYCLE_ERROR.value == "cycle_error"
        assert EventType.MARKETS_FETCHED.value == "markets_fetched"
        assert EventType.SIGNAL_GENERATED.value == "signal_generated"
        assert EventType.ORDER_FILLED.value == "order_filled"
        assert EventType.ORDER_REJECTED.value == "order_rejected"
        assert EventType.MARKET_SETTLED.value == "market_settled"
        assert EventType.MARKET_SCANNED.value == "market_scanned"
        assert EventType.EXIT_SIGNAL.value == "exit_signal"
        assert EventType.POSITION_CLOSED.value == "position_closed"


class TestEvent:
    def test_creation(self):
        e = Event(event_type=EventType.CYCLE_START, timestamp=1.0, data={"cycle": 1})
        assert e.event_type == EventType.CYCLE_START
        assert e.timestamp == 1.0
        assert e.data == {"cycle": 1}

    def test_frozen(self):
        e = Event(event_type=EventType.CYCLE_START, timestamp=1.0)
        with pytest.raises(AttributeError):
            e.timestamp = 2.0

    def test_default_data(self):
        e = Event(event_type=EventType.CYCLE_START, timestamp=1.0)
        assert e.data == {}


class TestEventBusEmitDrain:
    def test_emit_and_drain(self):
        bus = EventBus()
        bus.emit(EventType.CYCLE_START, cycle=1)
        bus.emit(EventType.CYCLE_END, cycle=1)

        events, cursor = bus.drain_from(0)
        assert len(events) == 2
        assert events[0].event_type == EventType.CYCLE_START
        assert events[0].data == {"cycle": 1}
        assert events[1].event_type == EventType.CYCLE_END
        assert cursor == 2

    def test_drain_empty_bus(self):
        bus = EventBus()
        events, cursor = bus.drain_from(0)
        assert events == []
        assert cursor == 0

    def test_drain_returns_only_new_events(self):
        bus = EventBus()
        bus.emit(EventType.CYCLE_START, cycle=1)
        bus.emit(EventType.CYCLE_END, cycle=1)

        _, cursor = bus.drain_from(0)

        bus.emit(EventType.CYCLE_START, cycle=2)
        events, cursor2 = bus.drain_from(cursor)
        assert len(events) == 1
        assert events[0].data == {"cycle": 2}
        assert cursor2 == 3

    def test_drain_at_current_cursor_returns_empty(self):
        bus = EventBus()
        bus.emit(EventType.CYCLE_START, cycle=1)
        _, cursor = bus.drain_from(0)

        events, cursor2 = bus.drain_from(cursor)
        assert events == []
        assert cursor2 == cursor


class TestEventBusTrimming:
    def test_trims_at_max_events(self):
        bus = EventBus(max_events=5)
        for i in range(10):
            bus.emit(EventType.CYCLE_START, cycle=i)

        events, cursor = bus.drain_from(0)
        assert len(events) == 5
        assert events[0].data == {"cycle": 5}
        assert cursor == 10

    def test_cursor_survives_trimming(self):
        bus = EventBus(max_events=5)
        for i in range(5):
            bus.emit(EventType.CYCLE_START, cycle=i)

        _, cursor = bus.drain_from(0)
        assert cursor == 5

        for i in range(5, 10):
            bus.emit(EventType.CYCLE_START, cycle=i)

        events, cursor2 = bus.drain_from(cursor)
        assert len(events) == 5
        assert events[0].data == {"cycle": 5}
        assert cursor2 == 10


class TestEventBusThreadSafety:
    def test_concurrent_emit_and_drain(self):
        bus = EventBus(max_events=500)
        errors = []

        def emitter(start: int):
            try:
                for i in range(100):
                    bus.emit(EventType.CYCLE_START, value=start + i)
            except Exception as e:
                errors.append(e)

        def drainer():
            try:
                cursor = 0
                for _ in range(50):
                    _, cursor = bus.drain_from(cursor)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=emitter, args=(0,)),
            threading.Thread(target=emitter, args=(100,)),
            threading.Thread(target=drainer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert bus.total_events == 200

    def test_emit_has_timestamp(self):
        bus = EventBus()
        bus.emit(EventType.CYCLE_START)
        events, _ = bus.drain_from(0)
        assert events[0].timestamp > 0
