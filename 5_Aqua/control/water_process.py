from __future__ import annotations

import logging
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
from control.empty_detection import EmptyDetectionSettings, EmptyDetector
from control.safety import SafetyLimits, SafetyMonitor, SafetyViolationError
from control.state_machine import ProcessState, ProcessStateMachine
from data.logger import CsvDataLogger
from data.models import ProcessEvent, ProcessSummary, SystemMeasurement
from data.repository import MeasurementRepository
from devices.bronkhorst import BronkhorstFlowController
from devices.lucid_ai4 import LucidAnalogInput
from devices.lucid_do import BinaryValve, LedController
from devices.sensors import CapacitanceScaling, HumidityScaling


LOGGER = logging.getLogger("aqua.control.water_process")


class WaterProcessError(RuntimeError):
    """Base error for process-control failures."""


class WaterProcessController:
    """Drives the gravity-fed drain process.

    The proportional valve is the manipulated variable and stays at a
    fixed opening (100 % by default) for the whole run. Measured flow is
    telemetry and is integrated into drained volume. The run normally
    ends when capacitance reports an empty vessel or the operator stops.

    Closed-loop flow control remains available through
    ``flow_setpoint_ml_min`` for diagnostics, but it is intentionally not
    part of the operator GUI workflow.
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
                "capacitance_channel and humidity_channel must differ."
            )

        self.bronkhorst = bronkhorst
        self.binary_valve = binary_valve
        self.led = led
        self.analog_inputs = analog_inputs
        self.logger = logger
        self.repository = repository
        self.state_machine = state_machine or ProcessStateMachine()
        self.safety_monitor = safety_monitor or SafetyMonitor(
            SafetyLimits(
                maximum_flow_ml_min=MAXIMUM_ALLOWED_FLOW_ML_MIN,
                critical_humidity_percent=CRITICAL_HUMIDITY_PERCENT,
            )
        )
        self.empty_detector = empty_detector or EmptyDetector()
        self.capacitance_scaling = capacitance_scaling or CapacitanceScaling()
        self.humidity_scaling = humidity_scaling or HumidityScaling()
        self.sample_interval_seconds = sample_interval_seconds
        self.capacitance_channel = capacitance_channel
        self.humidity_channel = humidity_channel

        self._stop_event = Event()
        self._valve_position_percent = 0.0
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
    def last_measurement(self) -> SystemMeasurement | None:
        """Return the latest acquired sample for diagnostics."""

        return self._last_measurement

    @property
    def empty_detection_settings(self) -> EmptyDetectionSettings:
        return self.empty_detector.settings

    def configure_empty_detection(self, settings: EmptyDetectionSettings) -> None:
        if self.state == ProcessState.RUNNING:
            raise WaterProcessError(
                "Empty detection cannot be reconfigured while the process is running."
            )
        self.empty_detector = EmptyDetector(settings)
        LOGGER.debug("Empty detection configured: %s", settings)

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

        log_method = {
            "DEBUG": LOGGER.debug,
            "INFO": LOGGER.info,
            "WARNING": LOGGER.warning,
            "ERROR": LOGGER.error,
            "CRITICAL": LOGGER.critical,
        }.get(severity.upper(), LOGGER.info)
        log_method("%s | %s", event_type, message)

    def connect(self) -> None:
        if self.state != ProcessState.DISCONNECTED:
            raise WaterProcessError(
                "Process can only connect from DISCONNECTED."
            )

        LOGGER.debug("Connecting Bronkhorst and confirming safe outputs")
        self.bronkhorst.connect()
        try:
            self._apply_safe_state()
        except Exception:
            try:
                self.bronkhorst.disconnect()
            finally:
                LOGGER.exception("Safe-state confirmation failed during connect")
            raise

        self.state_machine.mark_ready(
            "Devices connected and safe state confirmed."
        )

    def disconnect(self) -> None:
        if self.state in {ProcessState.RUNNING, ProcessState.STOPPING}:
            raise WaterProcessError(
                "Cannot disconnect while the process is running. Stop the run first."
            )

        safe_state_error: Exception | None = None
        try:
            self._apply_safe_state()
        except Exception as exc:
            safe_state_error = exc
            LOGGER.exception("Safe-state application failed during disconnect")
        finally:
            self.bronkhorst.disconnect()
            if self.state != ProcessState.DISCONNECTED:
                self.state_machine.mark_disconnected("Devices disconnected.")

        if safe_state_error is not None:
            raise WaterProcessError(
                "Hardware disconnected, but safe-state confirmation was incomplete."
            ) from safe_state_error

    def set_led(self, enabled: bool) -> None:
        if enabled:
            self.led.on()
        else:
            self.led.off()

    def request_stop(
        self,
        reason: str = "Manual stop requested.",
    ) -> None:
        """Thread-safely signal the blocking run loop to stop.

        This method may be called from the Qt GUI thread. It therefore
        deliberately avoids the CSV logger and repository; the worker
        thread persists the stop event after it leaves the run loop.
        """

        self._stop_reason = reason
        self._completed_successfully = True
        self._stop_event.set()
        LOGGER.debug("Stop event set: %s", reason)

    def start(
        self,
        *,
        valve_position_percent: float = DEFAULT_VALVE_POSITION_PERCENT,
        flow_setpoint_ml_min: float | None = None,
        duration_seconds: float | None = None,
        on_measurement: Callable[[SystemMeasurement], None] | None = None,
    ) -> ProcessSummary:
        """Run the drain process until empty, timed out, or stopped."""

        # A completed run is a normal reusable state. Re-arm explicitly so
        # the operator can start the next run without disconnect/reconnect.
        if self.state == ProcessState.STOPPED:
            self.state_machine.mark_ready("Process re-armed for the next run.")

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
        self.state_machine.mark_running("Water process started.")

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
                self.bronkhorst.set_flow_ml_min(flow_setpoint_ml_min)
                self._log_event(
                    event_type="PROCESS_STARTED",
                    severity="INFO",
                    message=(
                        "Diagnostic closed-loop draining started at "
                        f"{flow_setpoint_ml_min:.1f} ml/min."
                    ),
                )

            settings = self.empty_detector.settings
            empty_condition = (
                f"capacitance <= {settings.empty_threshold:g} scaled units for "
                f"{settings.consecutive_samples} consecutive samples"
            )
            if self.empty_detector.enabled:
                self._log_event(
                    event_type="EMPTY_DETECTION",
                    severity="INFO",
                    message=f"Automatic empty stop armed: {empty_condition}.",
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

                if self.empty_detector.update(measurement.capacitance_value):
                    self._stop_reason = f"Vessel empty: {empty_condition}."
                    self._completed_successfully = True
                    self._log_event(
                        event_type="EMPTY_STOP",
                        severity="INFO",
                        message=self._stop_reason,
                    )
                    break

                if (
                    duration_seconds is not None
                    and time.monotonic() - started_monotonic >= duration_seconds
                ):
                    self._stop_reason = "Configured duration reached."
                    self._completed_successfully = True
                    self._log_event(
                        event_type="DURATION_STOP",
                        severity="INFO",
                        message=self._stop_reason,
                    )
                    break

                time.sleep(self.sample_interval_seconds)

            if self._stop_event.is_set():
                self._log_event(
                    event_type="STOP_REQUESTED",
                    severity="INFO",
                    message=self._stop_reason or "Stop requested.",
                )

        except SafetyViolationError as exc:
            self._stop_reason = str(exc)
            self._completed_successfully = False
            self._log_event(
                event_type="SAFETY_FAULT",
                severity="ERROR",
                message=self._stop_reason,
            )
            self.state_machine.mark_fault(str(exc))

        except Exception as exc:
            self._stop_reason = f"Process error: {exc}"
            self._completed_successfully = False
            if self.state != ProcessState.FAULT:
                self.state_machine.mark_fault(self._stop_reason)
            try:
                self._log_event(
                    event_type="PROCESS_FAULT",
                    severity="ERROR",
                    message=self._stop_reason,
                )
            finally:
                LOGGER.exception("Unhandled process error")
            raise

        finally:
            self._shutdown_hardware()
            summary = self._build_summary()
            try:
                self.logger.log_summary(summary)
            finally:
                self.logger.finish_run()

        return summary

    def measure(self) -> SystemMeasurement:
        # One LucidIoCtrl call reads both AI channels. This keeps the two
        # sensor values temporally aligned and removes one subprocess per
        # telemetry sample.
        readings = self.analog_inputs.read_channel_voltages(
            (self.capacitance_channel, self.humidity_channel)
        )
        by_channel = {
            reading.channel: reading.voltage_v
            for reading in readings
        }
        capacitance_voltage = by_channel[self.capacitance_channel]
        humidity_voltage = by_channel[self.humidity_channel]

        capacitance_value = self.capacitance_scaling.to_value(
            capacitance_voltage
        )
        humidity_percent = self.humidity_scaling.to_percent(humidity_voltage)
        capacitance_state = self.empty_detector.settings.classify(
            capacitance_value
        )

        valve_output_raw = self.bronkhorst.read_valve_output_raw()
        valve_output_percent = (
            valve_output_raw
            / self.bronkhorst.VALVE_OUTPUT_FULL_SCALE
            * 100.0
        )

        return SystemMeasurement(
            timestamp=datetime.now(),
            flow_ml_min=self.bronkhorst.read_flow_ml_min(),
            flow_setpoint_ml_min=self.bronkhorst.read_flow_setpoint_ml_min(),
            bronkhorst_temperature_c=self.bronkhorst.read_temperature_c(),
            bronkhorst_alarm_info=self.bronkhorst.read_alarm_info(),
            bronkhorst_control_mode=self.bronkhorst.read_control_mode(),
            valve_output_raw=valve_output_raw,
            valve_output_raw_percent=valve_output_percent,
            valve_position_percent=self._valve_position_percent,
            capacitance_voltage_v=capacitance_voltage,
            capacitance_value=capacitance_value,
            capacitance_state=capacitance_state.value,
            humidity_voltage_v=humidity_voltage,
            humidity_percent=humidity_percent,
            binary_valve_open=self.binary_valve.is_open(refresh=False),
            led_on=self.led.is_on(refresh=False),
        )

    def _apply_safe_state(self) -> None:
        """Best-effort safe state: attempt both valve closures."""

        errors: list[Exception] = []
        if self.bronkhorst.is_connected:
            try:
                self.bronkhorst.force_valve_closed()
            except Exception as exc:
                errors.append(exc)
                LOGGER.exception("Could not close Bronkhorst proportional valve")

        try:
            self.binary_valve.close()
        except Exception as exc:
            errors.append(exc)
            LOGGER.exception("Could not close downstream binary valve")

        self._valve_position_percent = 0.0
        if errors:
            raise WaterProcessError(
                f"Safe state incomplete ({len(errors)} output error(s))."
            ) from errors[0]

    def _shutdown_hardware(self) -> None:
        if self.state == ProcessState.RUNNING:
            self.state_machine.mark_stopping(
                self._stop_reason or "Stopping."
            )

        try:
            self._apply_safe_state()
        except Exception as exc:
            self._stop_reason = f"Safe-state fault: {exc}"
            self._completed_successfully = False
            if self.state != ProcessState.FAULT:
                self.state_machine.mark_fault(self._stop_reason)
            try:
                self._log_event(
                    event_type="SAFE_STATE_FAULT",
                    severity="CRITICAL",
                    message=self._stop_reason,
                )
            except Exception:
                LOGGER.exception("Could not persist safe-state fault event")

        self._run_stopped_at = datetime.now()
        if self.state in {ProcessState.RUNNING, ProcessState.STOPPING}:
            self.state_machine.mark_stopped(
                self._stop_reason or "Process stopped."
            )

        if self.state == ProcessState.STOPPED:
            try:
                self._log_event(
                    event_type="PROCESS_STOPPED",
                    severity="INFO",
                    message=self._stop_reason or "Process stopped.",
                )
            except Exception:
                LOGGER.exception("Could not persist terminal process event")

    def _update_statistics(self, measurement: SystemMeasurement) -> None:
        self._flow_values.append(measurement.flow_ml_min)

        if measurement.capacitance_value is not None:
            self._capacitance_values.append(measurement.capacitance_value)
        if measurement.humidity_percent is not None:
            self._humidity_values.append(measurement.humidity_percent)

        if self._last_measurement is not None:
            delta_seconds = (
                measurement.timestamp - self._last_measurement.timestamp
            ).total_seconds()
            average_flow = (
                self._last_measurement.flow_ml_min + measurement.flow_ml_min
            ) / 2.0
            self._total_volume_ml += average_flow * delta_seconds / 60.0

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
            valve_position_percent=self._run_valve_position_percent,
            total_volume_ml=self._total_volume_ml,
            average_flow_ml_min=average_flow,
            minimum_flow_ml_min=(
                min(self._flow_values) if self._flow_values else 0.0
            ),
            maximum_flow_ml_min=(
                max(self._flow_values) if self._flow_values else 0.0
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
            stop_reason=self._stop_reason or "Process completed.",
            completed_successfully=self._completed_successfully,
        )
