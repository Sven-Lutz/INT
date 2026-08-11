from __future__ import annotations

from datetime import datetime

from control.empty_detection import CapacitanceState
from control.safety import (
    CriticalHumidityError,
    MaximumFlowError,
    SafetyLimits,
    SafetyMonitor,
)
from data.models import SystemMeasurement


def measurement(
    flow: float,
    *,
    humidity_percent: float | None = None,
) -> SystemMeasurement:
    return SystemMeasurement(
        timestamp=datetime.now(),
        flow_ml_min=flow,
        flow_setpoint_ml_min=0.0,
        bronkhorst_temperature_c=25.0,
        bronkhorst_alarm_info=0,
        bronkhorst_control_mode=20,
        valve_output_raw=0,
        valve_output_raw_percent=0.0,
        valve_position_percent=100.0,
        capacitance_voltage_v=None,
        capacitance_value=None,
        capacitance_state=CapacitanceState.UNKNOWN.value,
        humidity_voltage_v=None,
        humidity_percent=humidity_percent,
        binary_valve_open=True,
        led_on=False,
    )


def main() -> None:
    monitor = SafetyMonitor(
        SafetyLimits(maximum_flow_ml_min=200.0)
    )

    monitor.check(measurement(100.0))
    print("Valid measurement accepted.")

    try:
        monitor.check(measurement(250.0))
    except MaximumFlowError:
        print("Maximum flow correctly rejected.")
    else:
        raise AssertionError(
            "Expected MaximumFlowError."
        )

    # A low capacitance is the normal end of the drain process and must
    # never be treated as a safety violation.
    monitor.check(measurement(100.0))
    print("Low capacitance is not a safety violation.")

    humidity_monitor = SafetyMonitor(
        SafetyLimits(
            maximum_flow_ml_min=200.0,
            critical_humidity_percent=80.0,
        )
    )

    humidity_monitor.check(
        measurement(100.0, humidity_percent=40.0)
    )
    print("Humidity below limit accepted.")

    try:
        humidity_monitor.check(
            measurement(100.0, humidity_percent=95.0)
        )
    except CriticalHumidityError:
        print("Critical humidity correctly rejected.")
    else:
        raise AssertionError(
            "Expected CriticalHumidityError."
        )


if __name__ == "__main__":
    main()
