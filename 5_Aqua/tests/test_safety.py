from __future__ import annotations

from datetime import datetime

from control.safety import (
    MaximumFlowError,
    SafetyLimits,
    SafetyMonitor,
)
from data.models import SystemMeasurement


def measurement(flow: float) -> SystemMeasurement:
    return SystemMeasurement(
        timestamp=datetime.now(),
        flow_ml_min=flow,
        flow_setpoint_ml_min=100.0,
        bronkhorst_temperature_c=25.0,
        bronkhorst_alarm_info=0,
        bronkhorst_control_mode=0,
        valve_output_raw=0,
        valve_output_raw_percent=0.0,
        capacitance_voltage_v=None,
        capacitance_value=None,
        humidity_voltage_v=None,
        humidity_percent=None,
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


if __name__ == "__main__":
    main()
