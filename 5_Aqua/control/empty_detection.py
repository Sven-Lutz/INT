from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CapacitanceState(Enum):
    """Semantic fill state derived from the capacitance value."""

    UNKNOWN = "UNKNOWN"
    FILLED = "FILLED"
    DRAINING = "DRAINING"
    EMPTY = "EMPTY"


@dataclass(frozen=True)
class EmptyDetectionSettings:
    """Configuration of the capacitance-based empty detection.

    Draining always runs from full towards empty, so the only relevant
    condition is ``capacitance <= empty_threshold``. There is no
    "at or above" direction to choose.
    """

    empty_threshold: float = 2.0
    filled_threshold: float = 12.5
    consecutive_samples: int = 3
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.empty_threshold < 0.0:
            raise ValueError(
                "empty_threshold must not be negative."
            )

        if self.filled_threshold <= self.empty_threshold:
            raise ValueError(
                "filled_threshold must be greater than "
                "empty_threshold."
            )

        if self.consecutive_samples < 1:
            raise ValueError(
                "consecutive_samples must be at least 1."
            )

    def classify(
        self,
        capacitance_value: float | None,
    ) -> CapacitanceState:
        if capacitance_value is None:
            return CapacitanceState.UNKNOWN

        if capacitance_value <= self.empty_threshold:
            return CapacitanceState.EMPTY

        if capacitance_value >= self.filled_threshold:
            return CapacitanceState.FILLED

        return CapacitanceState.DRAINING


class EmptyDetector:
    """Debounced detector for "vessel has run empty".

    A single noisy sample below the threshold must not stop the process,
    so the detector only triggers after ``consecutive_samples`` readings
    in a row have stayed at or below the empty threshold.
    """

    def __init__(
        self,
        settings: EmptyDetectionSettings | None = None,
    ) -> None:
        self.settings = settings or EmptyDetectionSettings()
        self._below_threshold_count = 0
        self._state = CapacitanceState.UNKNOWN
        self._triggered = False

    @property
    def state(self) -> CapacitanceState:
        return self._state

    @property
    def below_threshold_count(self) -> int:
        return self._below_threshold_count

    @property
    def triggered(self) -> bool:
        return self._triggered

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def reset(self) -> None:
        self._below_threshold_count = 0
        self._state = CapacitanceState.UNKNOWN
        self._triggered = False

    def update(
        self,
        capacitance_value: float | None,
    ) -> bool:
        """Feeds one sample and reports whether the stop must fire."""

        self._state = self.settings.classify(capacitance_value)

        if capacitance_value is None:
            self._below_threshold_count = 0
            return False

        if capacitance_value <= self.settings.empty_threshold:
            self._below_threshold_count += 1
        else:
            self._below_threshold_count = 0

        reached = (
            self._below_threshold_count
            >= self.settings.consecutive_samples
        )

        if reached and self.settings.enabled:
            self._triggered = True

        return self._triggered

    def describe(self) -> str:
        return (
            f"Capacitance {self._state.value} "
            f"({self._below_threshold_count}/"
            f"{self.settings.consecutive_samples} samples at or "
            f"below {self.settings.empty_threshold:g})"
        )
