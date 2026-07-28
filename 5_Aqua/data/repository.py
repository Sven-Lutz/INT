from __future__ import annotations

from collections import deque
from threading import Lock

from data.models import (
    ProcessEvent,
    SystemMeasurement,
)


class MeasurementRepository:
    """Thread-safe in-memory storage for measurements and events."""

    def __init__(
        self,
        *,
        max_measurements: int = 10_000,
        max_events: int = 1_000,
    ) -> None:
        self._measurements: deque[SystemMeasurement] = deque(
            maxlen=max_measurements
        )
        self._events: deque[ProcessEvent] = deque(
            maxlen=max_events
        )
        self._lock = Lock()

    def add_measurement(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        with self._lock:
            self._measurements.append(measurement)

    def latest_measurement(
        self,
    ) -> SystemMeasurement | None:
        with self._lock:
            return (
                self._measurements[-1]
                if self._measurements
                else None
            )

    def recent_measurements(
        self,
        count: int = 100,
    ) -> list[SystemMeasurement]:
        with self._lock:
            return list(self._measurements)[-count:]

    def measurement_count(self) -> int:
        with self._lock:
            return len(self._measurements)

    def add_event(
        self,
        event: ProcessEvent,
    ) -> None:
        with self._lock:
            self._events.append(event)

    def latest_event(
        self,
    ) -> ProcessEvent | None:
        with self._lock:
            return self._events[-1] if self._events else None

    def recent_events(
        self,
        count: int = 100,
    ) -> list[ProcessEvent]:
        with self._lock:
            return list(self._events)[-count:]

    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    def clear(self) -> None:
        with self._lock:
            self._measurements.clear()
            self._events.clear()
