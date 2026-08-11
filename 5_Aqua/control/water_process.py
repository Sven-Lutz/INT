from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import Event, Lock
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
from control.run_configuration import ControlMode, RunConfiguration
from control.safety import SafetyLimits, SafetyMonitor, SafetyViolationError
from control.state_machine import ProcessState, ProcessStateMachine
from data.logger import CsvDataLogger
from data.models import ProcessEvent, ProcessSummary, SystemMeasurement
from data.repository import MeasurementRepository
from devices.bronkhorst import BronkhorstFlowController
from devices.lucid_ai4 import LucidAnalogInput
from devices.lucid_do import BinaryValve, LedController, LucidControlError
from devices.sensors import CapacitanceScaling, HumidityScaling


LOGGER = logging.getLogger("aqua.control.water_process")


class WaterProcessError(RuntimeError):
    """Base error for process-control failures."""


class LucidDigitalConfigurationError(WaterProcessError):
    """Critical Lucid digital configuration does not match Aqua safety."""


class _LiveCommandKind(Enum):
    VALVE_POSITION = "VALVE_POSITION"
    FLOW_TARGET = "FLOW_TARGET"
    LED = "LED"


@dataclass(frozen=True)
class _LiveCommand:
    kind: _LiveCommandKind
    value: float | bool


class WaterProcessController:
    """Drives the gravity-fed drain process.

    Each run uses either direct proportional-valve position or a closed-loop
    flow target. Empty detection and target run volume are independent stop
    conditions. Measured flow is integrated into both run-specific volume
    and a cumulative application-session total.
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
        self._active_flow_target_ml_min: float | None = None
        self._active_run_configuration: RunConfiguration | None = None
        self._run_started_at: datetime | None = None
        self._run_stopped_at: datetime | None = None
        self._last_measurement: SystemMeasurement | None = None
        self._total_volume_ml = 0.0
        self._session_total_volume_ml = 0.0
        self._flow_values: list[float] = []
        self._capacitance_values: list[float] = []
        self._humidity_values: list[float] = []
        self._stop_reason = ""
        self._completed_successfully = False
        self._lucid_digital_status = "DISCONNECTED"
        self._lucid_preflight_result = "NOT RUN"
        self._lucid_preflight_error: str | None = None
        self._lucid_channel_diagnostics: dict[str, dict[str, object]] = {}
        self._live_command_lock = Lock()
        self._pending_live_commands: deque[_LiveCommand] = deque()
        self._accept_live_commands = False

    @property
    def state(self) -> ProcessState:
        return self.state_machine.state

    @property
    def total_volume_ml(self) -> float:
        """Volume drained during the current or most recently completed run."""

        return self._total_volume_ml

    @property
    def run_volume_ml(self) -> float:
        return self._total_volume_ml

    @property
    def session_total_volume_ml(self) -> float:
        return self._session_total_volume_ml

    @property
    def active_control_mode(self) -> ControlMode | None:
        configuration = self._active_run_configuration
        return configuration.control_mode if configuration is not None else None

    @property
    def active_flow_target_ml_min(self) -> float | None:
        return self._active_flow_target_ml_min

    @property
    def pending_live_command_count(self) -> int:
        with self._live_command_lock:
            return len(self._pending_live_commands)

    @property
    def run_configuration_diagnostics(self) -> dict[str, object]:
        configuration = self._active_run_configuration
        if configuration is None:
            return {
                "control_mode": "—",
                "run_volume_ml": self._total_volume_ml,
                "session_total_volume_ml": self._session_total_volume_ml,
                "pending_live_commands": self.pending_live_command_count,
            }
        return {
            "control_mode": configuration.control_mode.value,
            "active_valve_position_percent": self._valve_position_percent,
            "active_flow_target_ml_min": self._active_flow_target_ml_min,
            "empty_stop_enabled": configuration.empty_stop_enabled,
            "empty_threshold": configuration.empty_threshold,
            "target_volume_enabled": configuration.target_volume_enabled,
            "target_volume_ml": configuration.target_volume_ml,
            "run_volume_ml": self._total_volume_ml,
            "session_total_volume_ml": self._session_total_volume_ml,
            "pending_live_commands": self.pending_live_command_count,
        }

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

    @property
    def lucid_digital_diagnostics(self) -> dict[str, object]:
        """Return cached commissioning data without performing hardware I/O."""

        channels: dict[str, dict[str, object]] = {}
        port = "—"
        last_communication_error: str | None = None
        actuators = (
            ("binary_valve", self.binary_valve, "Binary Valve"),
            ("led", self.led, "LED"),
        )
        for key, actuator, role in actuators:
            channel = getattr(actuator, "channel", None)
            entry = dict(self._lucid_channel_diagnostics.get(key, {}))
            entry.setdefault("role", role)
            entry.setdefault("channel", channel)
            entry.setdefault("expected_mode", "reflect")
            entry.setdefault("expected_inverted", False)
            if entry.get("port"):
                port = str(entry["port"])

            output = getattr(actuator, "controller", None)
            if output is not None:
                port = str(getattr(output, "port", port))
                diagnostic_reader = getattr(output, "channel_diagnostics", None)
                if callable(diagnostic_reader) and isinstance(channel, int):
                    entry.update(diagnostic_reader(channel))
                communication_error = getattr(
                    output,
                    "last_communication_error",
                    None,
                )
                if communication_error:
                    last_communication_error = str(communication_error)

            entry["cached_application_state"] = getattr(
                actuator,
                "last_known_state",
                None,
            )
            channels[key] = entry

        return {
            "port": port,
            "status": self._lucid_digital_status,
            "preflight": self._lucid_preflight_result,
            "preflight_error": self._lucid_preflight_error,
            "last_communication_error": last_communication_error,
            "channels": channels,
        }

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

        LOGGER.debug(
            "Connecting Bronkhorst, validating Lucid Digital, and "
            "confirming safe outputs"
        )
        self._lucid_digital_status = "CHECKING"
        self._lucid_preflight_result = "NOT RUN"
        self._lucid_preflight_error = None
        self._lucid_channel_diagnostics.clear()
        try:
            self.bronkhorst.connect()
        except Exception:
            self._lucid_digital_status = "DISCONNECTED"
            LOGGER.exception("Bronkhorst connection failed before Lucid preflight")
            raise

        lucid_preflight_valid = False
        try:
            self._preflight_lucid_digital_outputs()
            lucid_preflight_valid = True
            self._apply_safe_state()
            self.binary_valve.verify_closed()
        except Exception as exc:
            if isinstance(exc, LucidDigitalConfigurationError):
                self._lucid_digital_status = "CONFIG ERROR"
                self._lucid_preflight_result = "FAIL"
                self._lucid_preflight_error = str(exc)
            elif (
                self._exception_contains_lucid_error(exc)
                or not lucid_preflight_valid
                or self.binary_valve.last_known_state
                != self.binary_valve.closed_state
            ):
                self._lucid_digital_status = "COMM ERROR"
                self._lucid_preflight_result = "FAIL"
                self._lucid_preflight_error = str(exc)
            else:
                # The Lucid checks and verified binary safe state passed; a
                # different device (for example Bronkhorst) blocked READY.
                self._lucid_digital_status = "OK"
                self._lucid_preflight_result = "PASS"
                self._lucid_preflight_error = None
            if self.bronkhorst.is_connected:
                try:
                    self.bronkhorst.force_valve_closed()
                except Exception:
                    LOGGER.exception(
                        "Could not force Bronkhorst safe state after "
                        "connection failure"
                    )
            try:
                self.bronkhorst.disconnect()
            except Exception:
                LOGGER.exception(
                    "Bronkhorst cleanup failed after Lucid/safe-state preflight"
                )
            LOGGER.exception("Lucid/safe-state preflight failed during connect")
            raise

        self._lucid_digital_status = "OK"
        self._lucid_preflight_result = "PASS"
        self._lucid_preflight_error = None
        self.state_machine.mark_ready(
            "Devices connected and safe state confirmed."
        )

    def disconnect(self) -> None:
        if self.state in {ProcessState.RUNNING, ProcessState.STOPPING}:
            raise WaterProcessError(
                "Cannot disconnect while the process is running. Stop the run first."
            )
        if self.state == ProcessState.DISCONNECTED:
            return

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
            self._lucid_digital_status = "DISCONNECTED"
            self._lucid_preflight_result = "NOT RUN"

        if safe_state_error is not None:
            raise WaterProcessError(
                "Hardware disconnected, but safe-state confirmation was incomplete."
            ) from safe_state_error

    def _preflight_lucid_digital_outputs(self) -> None:
        """Require known reflect/non-inverted outputs before READY."""

        inspections = (
            ("binary_valve", self.binary_valve),
            ("led", self.led),
        )
        for key, actuator in inspections:
            try:
                details = actuator.preflight()
            except LucidControlError:
                raise
            except Exception as exc:
                raise LucidControlError(
                    f"Lucid Digital critical preflight read failed for {key}."
                ) from exc
            self._lucid_channel_diagnostics[key] = dict(details)

        for details in self._lucid_channel_diagnostics.values():
            port = str(details.get("port", "unknown port"))
            channel = details.get("channel", "?")
            role = details.get("role", "Digital Output")
            reported_mode = str(details.get("reported_mode", "unavailable"))
            if reported_mode.lower() != "reflect":
                raise LucidDigitalConfigurationError(
                    "Lucid Digital configuration error: "
                    f"{port} CH{channel} {role} expected "
                    f"outDiMode=reflect, received "
                    f"outDiMode={reported_mode}. The output cannot be "
                    "controlled safely until the hardware configuration "
                    "is corrected."
                )

            inverted = details.get("inverted")
            if inverted is not False:
                received = (
                    "on" if inverted is True else str(inverted)
                )
                raise LucidDigitalConfigurationError(
                    "Lucid Digital configuration error: "
                    f"{port} CH{channel} {role} expected "
                    f"outDiInverted=off, received "
                    f"outDiInverted={received}. The output cannot be "
                    "controlled safely until the hardware configuration "
                    "is corrected."
                )

    @staticmethod
    def _exception_contains_lucid_error(exc: BaseException) -> bool:
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            if isinstance(current, LucidControlError):
                return True
            visited.add(id(current))
            current = current.__cause__ or current.__context__
        return False

    def set_led(self, enabled: bool) -> None:
        """Apply an immediate LED command outside an active run."""

        if enabled:
            self.led.on()
        else:
            self.led.off()

    def request_led_change(self, enabled: bool) -> None:
        """Queue an LED command for execution by the active run thread."""

        self._queue_live_command(
            _LiveCommand(_LiveCommandKind.LED, bool(enabled))
        )

    def request_valve_position(self, percent: float) -> None:
        if not 0.0 <= percent <= 100.0:
            raise ValueError(
                "Valve position must be between 0 and 100 percent."
            )
        self._require_live_control_mode(ControlMode.VALVE_POSITION)
        self._queue_live_command(
            _LiveCommand(_LiveCommandKind.VALVE_POSITION, float(percent))
        )

    def request_flow_target(self, flow_ml_min: float) -> None:
        if flow_ml_min < 0.0:
            raise ValueError("Flow target must not be negative.")
        self._require_live_control_mode(ControlMode.FLOW_TARGET)
        self._queue_live_command(
            _LiveCommand(_LiveCommandKind.FLOW_TARGET, float(flow_ml_min))
        )

    def _require_live_control_mode(self, expected: ControlMode) -> None:
        configuration = self._active_run_configuration
        if configuration is None or configuration.control_mode != expected:
            active = (
                configuration.control_mode.value
                if configuration is not None
                else "NONE"
            )
            raise WaterProcessError(
                f"Live {expected.value} update rejected; active mode is {active}."
            )

    def _queue_live_command(self, command: _LiveCommand) -> None:
        with self._live_command_lock:
            if self.state != ProcessState.RUNNING or not self._accept_live_commands:
                raise WaterProcessError(
                    "Live command rejected because the process is not accepting "
                    "adjustments."
                )
            self._pending_live_commands.append(command)

    def _take_pending_live_commands(self) -> tuple[_LiveCommand, ...]:
        with self._live_command_lock:
            commands = tuple(self._pending_live_commands)
            self._pending_live_commands.clear()
        return commands

    def _apply_pending_live_commands(
        self,
        on_command_error: Callable[[str, str], None] | None,
    ) -> None:
        for command in self._take_pending_live_commands():
            if self._stop_event.is_set():
                return
            if command.kind == _LiveCommandKind.LED:
                requested = bool(command.value)
                previous = self.led.last_known_on
                try:
                    self.set_led(requested)
                    self._log_event(
                        event_type="LED_CHANGED",
                        severity="INFO",
                        message=(
                            f"LED {self._format_on_off(previous)} -> "
                            f"{self._format_on_off(requested)}."
                        ),
                    )
                except Exception as exc:
                    message = f"LED change failed: {exc}"
                    self._log_event(
                        event_type="LED_CHANGE_FAILED",
                        severity="ERROR",
                        message=message,
                    )
                    if on_command_error is not None:
                        on_command_error("LED command failed", message)
                continue

            if command.kind == _LiveCommandKind.VALVE_POSITION:
                requested_position = float(command.value)
                previous_position = self._valve_position_percent
                try:
                    self.bronkhorst.set_direct_valve_position(
                        requested_position
                    )
                except Exception as exc:
                    self._log_event(
                        event_type="VALVE_SETPOINT_CHANGE_FAILED",
                        severity="ERROR",
                        message=f"Valve position change failed: {exc}",
                    )
                    raise
                self._valve_position_percent = requested_position
                self._log_event(
                    event_type="VALVE_SETPOINT_CHANGED",
                    severity="INFO",
                    message=(
                        f"{previous_position:g} % -> "
                        f"{requested_position:g} %."
                    ),
                )
                continue

            requested_flow = float(command.value)
            previous_flow = self._active_flow_target_ml_min
            try:
                self.bronkhorst.set_flow_ml_min(requested_flow)
            except Exception as exc:
                self._log_event(
                    event_type="FLOW_SETPOINT_CHANGE_FAILED",
                    severity="ERROR",
                    message=f"Flow target change failed: {exc}",
                )
                raise
            self._active_flow_target_ml_min = requested_flow
            previous_text = "—" if previous_flow is None else f"{previous_flow:g}"
            self._log_event(
                event_type="FLOW_SETPOINT_CHANGED",
                severity="INFO",
                message=f"{previous_text} ml/min -> {requested_flow:g} ml/min.",
            )

    @staticmethod
    def _format_on_off(value: bool | None) -> str:
        if value is None:
            return "UNKNOWN"
        return "ON" if value else "OFF"

    def request_stop(
        self,
        reason: str = "Manual stop requested.",
    ) -> None:
        """Thread-safely signal the blocking run loop to stop.

        This method may be called from the Qt GUI thread. It therefore
        deliberately avoids the CSV logger and repository; the worker
        thread persists the stop event after it leaves the run loop.
        """

        with self._live_command_lock:
            self._accept_live_commands = False
            self._pending_live_commands.clear()
            self._stop_reason = reason
            self._completed_successfully = True
        self._stop_event.set()
        LOGGER.debug("Stop event set: %s", reason)

    def start(
        self,
        *,
        configuration: RunConfiguration | None = None,
        valve_position_percent: float = DEFAULT_VALVE_POSITION_PERCENT,
        flow_setpoint_ml_min: float | None = None,
        target_volume_ml: float | None = None,
        duration_seconds: float | None = None,
        on_measurement: Callable[[SystemMeasurement], None] | None = None,
        on_started: Callable[[], None] | None = None,
        on_command_error: Callable[[str, str], None] | None = None,
    ) -> ProcessSummary:
        """Run the drain process until empty, timed out, or stopped."""

        if configuration is None:
            settings = self.empty_detector.settings
            configuration = RunConfiguration(
                control_mode=(
                    ControlMode.VALVE_POSITION
                    if flow_setpoint_ml_min is None
                    else ControlMode.FLOW_TARGET
                ),
                valve_position_percent=valve_position_percent,
                flow_target_ml_min=(
                    0.0
                    if flow_setpoint_ml_min is None
                    else flow_setpoint_ml_min
                ),
                empty_stop_enabled=settings.enabled,
                empty_threshold=settings.empty_threshold,
                target_volume_enabled=target_volume_ml is not None,
                target_volume_ml=(
                    1.0 if target_volume_ml is None else target_volume_ml
                ),
            )

        # A completed run is a normal reusable state. Re-arm explicitly so
        # the operator can start the next run without disconnect/reconnect.
        if self.state == ProcessState.STOPPED:
            self.state_machine.mark_ready("Process re-armed for the next run.")

        if not self.state_machine.is_ready:
            raise WaterProcessError(
                "Process must be READY before starting."
            )

        current_empty_settings = self.empty_detector.settings
        self.configure_empty_detection(
            EmptyDetectionSettings(
                empty_threshold=configuration.empty_threshold,
                filled_threshold=current_empty_settings.filled_threshold,
                consecutive_samples=(
                    current_empty_settings.consecutive_samples
                ),
                enabled=configuration.empty_stop_enabled,
            )
        )

        self._active_run_configuration = configuration
        direct_valve_mode = (
            configuration.control_mode == ControlMode.VALVE_POSITION
        )
        self._valve_position_percent = (
            configuration.valve_position_percent
            if direct_valve_mode
            else 0.0
        )
        self._run_valve_position_percent = self._valve_position_percent
        self._active_flow_target_ml_min = (
            configuration.flow_target_ml_min
            if not direct_valve_mode
            else None
        )
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
        with self._live_command_lock:
            self._pending_live_commands.clear()
            self._accept_live_commands = False

        self.logger.start_run()
        self._stop_event.clear()
        self.state_machine.mark_running("Water process started.")
        with self._live_command_lock:
            self._accept_live_commands = True

        try:
            if on_started is not None:
                on_started()
            self.binary_valve.open()

            if direct_valve_mode:
                self.bronkhorst.set_direct_valve_position(
                    configuration.valve_position_percent
                )
                self._log_event(
                    event_type="PROCESS_STARTED",
                    severity="INFO",
                    message=(
                        "Draining started with valve at "
                        f"{configuration.valve_position_percent:.0f} %."
                    ),
                )
            else:
                self.bronkhorst.set_flow_ml_min(
                    configuration.flow_target_ml_min
                )
                self._log_event(
                    event_type="PROCESS_STARTED",
                    severity="INFO",
                    message=(
                        "Closed-loop draining started at "
                        f"{configuration.flow_target_ml_min:.1f} ml/min."
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
            if configuration.target_volume_enabled:
                self._log_event(
                    event_type="TARGET_VOLUME_ARMED",
                    severity="INFO",
                    message=(
                        "Target-volume stop armed at "
                        f"{configuration.target_volume_ml:.1f} ml run volume."
                    ),
                )

            started_monotonic = time.monotonic()
            while not self._stop_event.is_set():
                self._apply_pending_live_commands(on_command_error)
                measurement = self.measure()
                self.safety_monitor.check(measurement)

                self.repository.add_measurement(measurement)
                self.logger.log_measurement(measurement)
                self._update_statistics(measurement)

                if on_measurement is not None:
                    on_measurement(measurement)

                if self._stop_event.is_set():
                    break

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
                    configuration.target_volume_enabled
                    and self._total_volume_ml
                    >= configuration.target_volume_ml
                ):
                    self._stop_reason = (
                        "Target drained volume reached: "
                        f"{self._total_volume_ml:.1f} ml >= "
                        f"{configuration.target_volume_ml:.1f} ml."
                    )
                    self._completed_successfully = True
                    self._log_event(
                        event_type="VOLUME_STOP",
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
            with self._live_command_lock:
                self._accept_live_commands = False
                self._pending_live_commands.clear()
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
            drained_volume_ml = average_flow * delta_seconds / 60.0
            self._total_volume_ml += drained_volume_ml
            self._session_total_volume_ml += drained_volume_ml

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
