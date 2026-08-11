from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapacitanceScaling:
    """Converts an AI4 voltage into the capacitance process value.

    The sensor behaves almost binary: roughly ``full_value`` while water
    is present and roughly zero once the vessel has run empty. The
    conversion is therefore kept deliberately simple and linear.
    """

    value_per_volt: float = 1.0
    offset: float = 0.0
    full_value: float = 25.0

    def __post_init__(self) -> None:
        if self.value_per_volt == 0.0:
            raise ValueError(
                "value_per_volt must not be zero."
            )

        if self.full_value <= 0.0:
            raise ValueError(
                "full_value must be greater than zero."
            )

    def to_value(
        self,
        voltage_v: float | None,
    ) -> float | None:
        if voltage_v is None:
            return None

        return voltage_v * self.value_per_volt + self.offset


@dataclass(frozen=True)
class HumidityScaling:
    """Converts an AI4 voltage into relative humidity in percent."""

    voltage_at_0_percent: float = 0.0
    voltage_at_100_percent: float = 10.0
    clamp_to_range: bool = True

    def __post_init__(self) -> None:
        if (
            self.voltage_at_0_percent
            == self.voltage_at_100_percent
        ):
            raise ValueError(
                "voltage_at_0_percent and voltage_at_100_percent "
                "must differ."
            )

    def to_percent(
        self,
        voltage_v: float | None,
    ) -> float | None:
        if voltage_v is None:
            return None

        span = (
            self.voltage_at_100_percent
            - self.voltage_at_0_percent
        )

        percent = (
            (voltage_v - self.voltage_at_0_percent)
            / span
            * 100.0
        )

        if not self.clamp_to_range:
            return percent

        return min(100.0, max(0.0, percent))
