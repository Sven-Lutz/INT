from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SystemMeasurement:
    timestamp: datetime

    flow_ml_min: float
    flow_setpoint_ml_min: float

    bronkhorst_temperature_c: float
    bronkhorst_alarm_info: int
    bronkhorst_control_mode: int
    valve_output_raw: int
    valve_output_raw_percent: float

    capacitance_voltage_v: float | None
    capacitance_value: float | None

    humidity_voltage_v: float | None
    humidity_percent: float | None

    binary_valve_open: bool
    led_on: bool


@dataclass(frozen=True)
class ProcessEvent:
    timestamp: datetime
    event_type: str
    severity: str
    message: str


@dataclass(frozen=True)
class ProcessSummary:
    started_at: datetime
    stopped_at: datetime
    duration_seconds: float
    target_flow_ml_min: float
    total_volume_ml: float
    average_flow_ml_min: float
    minimum_flow_ml_min: float
    maximum_flow_ml_min: float
    maximum_capacitance_value: float | None
    maximum_humidity_percent: float | None
    stop_reason: str
    completed_successfully: bool
