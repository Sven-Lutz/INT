from __future__ import annotations

import time
from datetime import datetime
from threading import Event
from typing import Callable

from config import (
    CAPACITANCE_CHANNEL,
    CRITICAL_HUMIDITY_PERCENT,
    DEFAULT_VALVE_POSITION_PERCENT,
    HUMIDITY_CHANNEL,
    MAXIMUM_ALLOWED_FLOW_ML_MIN,
    SAMPLE_INTERVAL_SECONDS,
)

from control.empty_detection import (
    EmptyDetectionSettings,
    EmptyDetector,
)
from control.safety import (
    SafetyLimits,
    SafetyMonitor,
    SafetyViolationError,
)
from control.state_machine import (
    ProcessState,
    ProcessStateMachine,
)
from data.logger import CsvDataLogger
from data.models import (
    ProcessEvent,
    ProcessSummary,
    SystemMeasurement,
)
from data.repository import MeasurementRepository
from devices.bronkhorst import BronkhorstFlowController
from devices.lucid_ai4 import LucidAnalogInput
from devices.lucid_do import BinaryValve, LedController
from devices.sensors import CapacitanceScaling, HumidityScaling


class WaterProcessError(RuntimeError):
    """Base error for process-control failures."""


class WaterProcessController:
    """Drives the gravity-fed drain process.

    The proportional valve is the manipulated variable and stays at a
    fixed opening (100 % by default) for the whole run. The measured
    flow is telemetry and is integrated into a drained volume. The run
    ends when the capacitance sensor reports an empty vessel, when a
    configured duration elapses, or on a manual stop.

    Closed-loop flow control is still available through
    ``flow_setpoint_ml_min`` but is not part of the operator workflow.
    """

    def __init__(
        self,
        *,
        bronkhorst: BronkhorstFlowController,
        binary_valve: BinaryValve,
        led: LedController,
        analog_inputs: LucidAnalogInput,
        logger: CsvDataLogger,
        repository: MeasurementRepository,
        state_machine: ProcessStateMachine | None = None,
        safety_monitor: SafetyMonitor | None = None,
        empty_detector: EmptyDetector | None = None,
        capacitance_scaling: CapacitanceScaling | None = None,
        humidity_scaling: HumidityScaling | None = None,
        sample_interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
        capacitance_channel: int = CAPACITANCE_CHANNEL,
        humidity_channel: int = HUMIDITY_CHANNEL,
    ) -> None:
        if capacitance_channel == humidity_channel:
            raise ValueError(
                "capacitance_channel and humidity_channel must "
                "differ."
            )

        self.bronkhorst = bronkhorst
        self.binary_valve = binary_valve
        self.led = led
        self.analog_inputs = analog_inputs
        self.logger = logger
        self.repository = repository
        self.state_machine = (
            state_machine or ProcessStateMachine()
        )
        self.safety_monitor = (
            safety_monitor
            or SafetyMonitor(
                SafetyLimits(
                    maximum_flow_ml_min=MAXIMUM_ALLOWED_FLOW_ML_MIN,
                    critical_humidity_percent=CRITICAL_HUMIDITY_PERCENT,
                )
            )
        )
        self.empty_detector = (
            empty_detector or EmptyDetector()
        )
        self.capacitance_scaling = (
            capacitance_scaling or CapacitanceScaling()
        )
        self.humidity_scaling = (
            humidity_scaling or HumidityScaling()
        )

        self.sample_interval_seconds = sample_interval_seconds
        self.capacitance_channel = capacitance_channel
        self.humidity_channel = humidity_channel

        self._stop_event = Event()

        # Currently commanded opening, zero in the safe state.
        self._valve_position_percent = 0.0

        # Opening configured for the active run, kept for the summary.
        self._run_valve_position_percent = 0.0

        self._run_started_at: datetime | None = None
        self._run_stopped_at: datetime | None = None
        self._last_measurement: SystemMeasurement | None = None
        self._total_volume_ml = 0.0
        self._flow_values: list[float] = []
        self._capacitance_values: list[float] = []
        self._humidity_values: list[float] = []
        self._stop_reason = ""
        self._completed_successfully = False

    @property
    def state(self) -> ProcessState:
        return self.state_machine.state

    @property
    def total_volume_ml(self) -> float:
        return self._total_volume_ml

    @property
    def valve_position_percent(self) -> float:
        return self._valve_position_percent

    @property
    def empty_detection_settings(self) -> EmptyDetectionSettings:
        return self.empty_detector.settings

    def configure_empty_detection(
        self,
        settings: EmptyDetectionSettings,
    ) -> None:
        """Replaces the empty-detection settings between runs."""

        if self.state == ProcessState.RUNNING:
            raise WaterProcessError(
                "Empty detection cannot be reconfigured while the "
                "process is running."
            )

        self.empty_detector = EmptyDetector(settings)

    def _log_event(
        self,
        *,
        event_type: str,
        severity: str,
        message: str,
    ) -> None:
        event = ProcessEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            severity=severity,
            message=message,
        )
        self.repository.add_event(event)

        if self.logger.run_started:
            self.logger.log_event(event)

    def connect(self) -> None:
        if self.state != ProcessState.DISCONNECTED:
            raise WaterProcessError(
                "Process can only connect from DISCONNECTED."
            )

        self.bronkhorst.connect()
        self._apply_safe_state()
        self.state_machine.mark_ready(
            "Devices connected and safe state confirmed."
        )

    def disconnect(self) -> None:
        if self.state == ProcessState.RUNNING:
            self.request_stop("Disconnect requested.")

        self._apply_safe_state()
        self.bronkhorst.disconnect()

        if self.state != ProcessState.DISCONNECTED:
            self.state_machine.mark_disconnected(
                "Devices disconnected."
            )

    def set_led(self, enabled: bool) -> None:
        if enabled:
            self.led.on()
        else:
            self.led.off()

    def request_stop(
        self,
        reason: str = "Manual stop requested.",
    ) -> None:
        self._stop_reason = reason
        self._completed_successfully = True
        self._stop_event.set()

    def start(
        self,
        *,
        valve_position_percent: float = (
            DEFAULT_VALVE_POSITION_PERCENT
        ),
        flow_setpoint_ml_min: float | None = None,
        duration_seconds: float | None = None,
        on_measurement: (
            Callable[[SystemMeasurement], None] | None
        ) = None,
    ) -> ProcessSummary:
        """Runs the drain process until it is empty or stopped.

        ``flow_setpoint_ml_min`` switches the Bronkhorst into
        closed-loop flow control instead of a fixed valve opening. It is
        kept for diagnostics and is not used by the GUI.
        """

        if not self.state_machine.is_ready:
            raise WaterProcessError(
                "Process must be READY before starting."
            )

        if not 0.0 <= valve_position_percent <= 100.0:
            raise ValueError(
                "valve_position_percent must be between 0 and 100."
            )

        self._valve_position_percent = valve_position_percent
        self._run_valve_position_percent = valve_position_percent
        self._run_started_at = datetime.now()
        self._run_stopped_at = None
        self._last_measurement = None
        self._total_volume_ml = 0.0
        self._flow_values.clear()
        self._capacitance_values.clear()
        self._humidity_values.clear()
        self._stop_reason = ""
        self._completed_successfully = False
        self.empty_detector.reset()

        self.logger.start_run()
        self._stop_event.clear()
        self.state_machine.mark_running(
            "Water process started."
        )

        try:
            self.binary_valve.open()

            if flow_setpoint_ml_min is None:
                self.bronkhorst.set_direct_valve_position(
                    valve_position_percent
                )
                self._log_event(
                    event_type="PROCESS_STARTED",
                    severity="INFO",
                    message=(
                        "Draining started with valve at "
                        f"{valve_position_percent:.0f} %."
                    ),
                )
            else:
                self.bronkhorst.set_flow_ml_min(
                    flow_setpoint_ml_min
                )
                self._log_event(
                    event_type="PROCESS_STARTED",
                    severity="INFO",
                    message=(
                        "Draining started in closed-loop mode at "
                        f"{flow_setpoint_ml_min:.1f} ml/min."
                    ),
                )

            settings = self.empty_detector.settings
            empty_condition = (
                f"capacitance <= {settings.empty_threshold:g} "
                f"for {settings.consecutive_samples} "
                "consecutive samples"
            )

            if self.empty_detector.enabled:
                self._log_event(
                    event_type="EMPTY_DETECTION",
                    severity="INFO",
                    message=(
                        "Automatic empty stop armed: "
                        f"{empty_condition}."
                    ),
                )

            started_monotonic = time.monotonic()

            while not self._stop_event.is_set():
                measurement = self.measure()
                self.safety_monitor.check(measurement)

                self.repository.add_measurement(measurement)
                self.logger.log_measurement(measurement)
                self._update_statistics(measurement)

                if on_measurement is not None:
                    on_measurement(measurement)

                if self.empty_detector.update(
                    measurement.capacitance_value
                ):
                    self._stop_reason = (
                        f"Vessel empty: {empty_condition}."
                    )
                    self._completed_successfully = True
                    self._log_event(
                        event_type="EMPTY_STOP",
                        severity="INFO",
                        message=self._stop_reason,
                    )
                    break

                if duration_seconds is not None:
                    if (
                        time.monotonic() - started_monotonic
                        >= duration_seconds
                    ):
                        self._stop_reason = (
                            "Configured duration reached."
                        )
                        self._completed_successfully = True
                        break

                time.sleep(self.sample_interval_seconds)

        except SafetyViolationError as exc:
            self._stop_reason = str(exc)
            self.state_machine.mark_fault(str(exc))

        finally:
            self._shutdown_hardware()
            summary = self._build_summary()
            self.logger.log_summary(summary)
            self.logger.finish_run()

        return summary

    def measure(self) -> SystemMeasurement:
        capacitance_voltage = (
            self.analog_inputs.read_channel_voltage(
                self.capacitance_channel
            )
        )

        humidity_voltage = (
            self.analog_inputs.read_channel_voltage(
                self.humidity_channel
            )
        )

        capacitance_value = self.capacitance_scaling.to_value(
            capacitance_voltage
        )
        humidity_percent = self.humidity_scaling.to_percent(
            humidity_voltage
        )

        capacitance_state = (
            self.empty_detector.settings.classify(
                capacitance_value
            )
        )

        return SystemMeasurement(
            timestamp=datetime.now(),
            flow_ml_min=self.bronkhorst.read_flow_ml_min(),
            flow_setpoint_ml_min=(
                self.bronkhorst.read_flow_setpoint_ml_min()
            ),
            bronkhorst_temperature_c=(
                self.bronkhorst.read_temperature_c()
            ),
            bronkhorst_alarm_info=(
                self.bronkhorst.read_alarm_info()
            ),
            bronkhorst_control_mode=(
                self.bronkhorst.read_control_mode()
            ),
            valve_output_raw=(
                self.bronkhorst.read_valve_output_raw()
            ),
            valve_output_raw_percent=(
                self.bronkhorst.read_valve_output_raw_percent()
            ),
            valve_position_percent=self._valve_position_percent,
            capacitance_voltage_v=capacitance_voltage,
            capacitance_value=capacitance_value,
            capacitance_state=capacitance_state.value,
            humidity_voltage_v=humidity_voltage,
            humidity_percent=humidity_percent,
            binary_valve_open=self.binary_valve.is_open(),
            led_on=self.led.is_on(),
        )

    def _apply_safe_state(self) -> None:
        if self.bronkhorst.is_connected:
            self.bronkhorst.force_valve_closed()
        self.binary_valve.close()
        self._valve_position_percent = 0.0

    def _shutdown_hardware(self) -> None:
        if self.state == ProcessState.RUNNING:
            self.state_machine.mark_stopping(
                self._stop_reason or "Stopping."
            )

        self._apply_safe_state()
        self._run_stopped_at = datetime.now()

        if self.state in {
            ProcessState.RUNNING,
            ProcessState.STOPPING,
        }:
            self.state_machine.mark_stopped(
                self._stop_reason or "Process stopped."
            )

    def _update_statistics(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        self._flow_values.append(measurement.flow_ml_min)

        if measurement.capacitance_value is not None:
            self._capacitance_values.append(
                measurement.capacitance_value
            )

        if measurement.humidity_percent is not None:
            self._humidity_values.append(
                measurement.humidity_percent
            )

        if self._last_measurement is not None:
            delta_seconds = (
                measurement.timestamp
                - self._last_measurement.timestamp
            ).total_seconds()

            average_flow = (
                self._last_measurement.flow_ml_min
                + measurement.flow_ml_min
            ) / 2.0

            self._total_volume_ml += (
                average_flow * delta_seconds / 60.0
            )

        self._last_measurement = measurement

    def _build_summary(self) -> ProcessSummary:
        started = self._run_started_at or datetime.now()
        stopped = self._run_stopped_at or datetime.now()

        average_flow = (
            sum(self._flow_values) / len(self._flow_values)
            if self._flow_values
            else 0.0
        )

        return ProcessSummary(
            started_at=started,
            stopped_at=stopped,
            duration_seconds=(stopped - started).total_seconds(),
            valve_position_percent=(
                self._run_valve_position_percent
            ),
            total_volume_ml=self._total_volume_ml,
            average_flow_ml_min=average_flow,
            minimum_flow_ml_min=(
                min(self._flow_values)
                if self._flow_values
                else 0.0
            ),
            maximum_flow_ml_min=(
                max(self._flow_values)
                if self._flow_values
                else 0.0
            ),
            minimum_capacitance_value=(
                min(self._capacitance_values)
                if self._capacitance_values
                else None
            ),
            final_capacitance_value=(
                self._capacitance_values[-1]
                if self._capacitance_values
                else None
            ),
            maximum_humidity_percent=(
                max(self._humidity_values)
                if self._humidity_values
                else None
            ),
            stop_reason=(
                self._stop_reason or "Process completed."
            ),
            completed_successfully=(
                self._completed_successfully
            ),
        )
