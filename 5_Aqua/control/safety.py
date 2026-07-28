from __future__ import annotations

import math
from dataclasses import dataclass

from data.models import SystemMeasurement


class SafetyViolationError(RuntimeError):
    """Base error for all process safety violations."""


class CriticalCapacitanceError(SafetyViolationError):
    pass


class CriticalHumidityError(SafetyViolationError):
    pass


class MaximumFlowError(SafetyViolationError):
    pass


class BronkhorstAlarmError(SafetyViolationError):
    pass


class InvalidMeasurementError(SafetyViolationError):
    pass


@dataclass(frozen=True)
class SafetyLimits:
    maximum_flow_ml_min: float
    critical_capacitance_value: float | None = None
    critical_humidity_percent: float | None = None
    stop_on_any_bronkhorst_alarm: bool = True

    def __post_init__(self) -> None:
        if self.maximum_flow_ml_min <= 0:
            raise ValueError(
                "maximum_flow_ml_min must be greater than zero."
            )


class SafetyMonitor:
    def __init__(self, limits: SafetyLimits) -> None:
        self.limits = limits

    def check(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        self._check_finite(measurement)
        self._check_flow(measurement)
        self._check_capacitance(measurement)
        self._check_humidity(measurement)
        self._check_alarm(measurement)

    @staticmethod
    def _check_finite(
        measurement: SystemMeasurement,
    ) -> None:
        required = (
            measurement.flow_ml_min,
            measurement.flow_setpoint_ml_min,
            measurement.bronkhorst_temperature_c,
            measurement.valve_output_raw_percent,
        )

        if not all(math.isfinite(value) for value in required):
            raise InvalidMeasurementError(
                "At least one required measurement is not finite."
            )

    def _check_flow(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        if (
            measurement.flow_ml_min
            > self.limits.maximum_flow_ml_min
        ):
            raise MaximumFlowError(
                "Maximum permitted flow exceeded."
            )

    def _check_capacitance(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        limit = self.limits.critical_capacitance_value

        if limit is None:
            return

        value = measurement.capacitance_value

        if value is None:
            raise InvalidMeasurementError(
                "Capacitance monitoring is enabled, "
                "but no calibrated value is available."
            )

        if value >= limit:
            raise CriticalCapacitanceError(
                "Critical capacitance limit reached."
            )

    def _check_humidity(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        limit = self.limits.critical_humidity_percent

        if limit is None:
            return

        value = measurement.humidity_percent

        if value is None:
            raise InvalidMeasurementError(
                "Humidity monitoring is enabled, "
                "but no calibrated value is available."
            )

        if value >= limit:
            raise CriticalHumidityError(
                "Critical humidity limit reached."
            )

    def _check_alarm(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        if (
            self.limits.stop_on_any_bronkhorst_alarm
            and measurement.bronkhorst_alarm_info != 0
        ):
            raise BronkhorstAlarmError(
                "Bronkhorst reported an alarm condition."
            )
