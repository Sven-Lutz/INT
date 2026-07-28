from __future__ import annotations

from typing import Any

import propar


class BronkhorstError(RuntimeError):
    """Base error for Bronkhorst communication and control failures."""


class BronkhorstFlowController:
    # ProPar parameter IDs
    PARAM_SETPOINT_RAW = 9
    PARAM_CONTROL_MODE = 12
    PARAM_ALARM_INFO = 28
    PARAM_VALVE_OUTPUT = 55
    PARAM_TEMPERATURE = 142
    PARAM_FLOW = 205
    PARAM_FLOW_SETPOINT = 206

    # Control modes
    MODE_DIGITAL_CONTROL = 0
    MODE_ANALOG_CONTROL = 1
    MODE_VALVE_CLOSE = 3
    MODE_VALVE_FULLY_OPEN = 8
    MODE_VALVE_STEERING = 20

    SETPOINT_FULL_SCALE = 32_000
    VALVE_OUTPUT_FULL_SCALE = 16_777_215

    def __init__(
        self,
        port: str,
        node_address: int,
        baudrate: int,
    ) -> None:
        if not port:
            raise ValueError(
                "Bronkhorst port must not be empty."
            )

        if node_address < 0:
            raise ValueError(
                "Bronkhorst node address must not be negative."
            )

        if baudrate <= 0:
            raise ValueError(
                "Bronkhorst baudrate must be greater than zero."
            )

        self.port = port
        self.node_address = node_address
        self.baudrate = baudrate
        self._instrument: Any | None = None

    @property
    def is_connected(self) -> bool:
        return self._instrument is not None

    def connect(self) -> None:
        if self.is_connected:
            return

        try:
            self._instrument = propar.instrument(
                self.port,
                self.node_address,
                baudrate=self.baudrate,
            )
            self.read_control_mode()
        except Exception as exc:
            self._instrument = None
            raise BronkhorstError(
                "Could not connect to Bronkhorst on "
                f"{self.port}, node {self.node_address}, "
                f"{self.baudrate} baud."
            ) from exc

    def disconnect(self) -> None:
        if self._instrument is None:
            return

        try:
            self._instrument.master.close()
        finally:
            self._instrument = None

    def _require_connection(self) -> Any:
        if self._instrument is None:
            raise BronkhorstError(
                "Bronkhorst is not connected."
            )
        return self._instrument

    def read_parameter(self, parameter: int) -> Any:
        try:
            return self._require_connection().readParameter(parameter)
        except Exception as exc:
            raise BronkhorstError(
                f"Could not read Bronkhorst parameter {parameter}."
            ) from exc

    def write_parameter(
        self,
        parameter: int,
        value: int | float,
        *,
        verify: bool = True,
        tolerance: float = 1e-4,
    ) -> None:
        instrument = self._require_connection()

        try:
            result = instrument.writeParameter(
                parameter,
                value,
            )
        except Exception as exc:
            raise BronkhorstError(
                f"Could not write Bronkhorst parameter "
                f"{parameter} with value {value}."
            ) from exc

        if result is False:
            raise BronkhorstError(
                f"Bronkhorst rejected parameter "
                f"{parameter} with value {value}."
            )

        if not verify:
            return

        readback = self.read_parameter(parameter)

        if abs(float(readback) - float(value)) > tolerance:
            raise BronkhorstError(
                f"Bronkhorst read-back failed for parameter "
                f"{parameter}: expected {value}, received {readback}."
            )

    def read_flow_ml_min(self) -> float:
        return float(self.read_parameter(self.PARAM_FLOW))

    def read_flow_setpoint_ml_min(self) -> float:
        return float(
            self.read_parameter(self.PARAM_FLOW_SETPOINT)
        )

    def read_temperature_c(self) -> float:
        return float(
            self.read_parameter(self.PARAM_TEMPERATURE)
        )

    def read_alarm_info(self) -> int:
        return int(
            self.read_parameter(self.PARAM_ALARM_INFO)
        )

    def read_control_mode(self) -> int:
        return int(
            self.read_parameter(self.PARAM_CONTROL_MODE)
        )

    def read_valve_output_raw(self) -> int:
        return int(
            self.read_parameter(self.PARAM_VALVE_OUTPUT)
        )

    def read_valve_output_raw_percent(self) -> float:
        return (
            self.read_valve_output_raw()
            / self.VALVE_OUTPUT_FULL_SCALE
            * 100.0
        )

    def set_flow_ml_min(self, flow_ml_min: float) -> None:
        if flow_ml_min < 0:
            raise ValueError(
                "Flow setpoint must not be negative."
            )

        self.write_parameter(
            self.PARAM_CONTROL_MODE,
            self.MODE_DIGITAL_CONTROL,
        )

        self.write_parameter(
            self.PARAM_FLOW_SETPOINT,
            flow_ml_min,
            tolerance=0.01,
        )

    def force_valve_open(self) -> None:
        self.write_parameter(
            self.PARAM_CONTROL_MODE,
            self.MODE_VALVE_FULLY_OPEN,
        )

    def force_valve_closed(self) -> None:
        instrument = self._require_connection()

        try:
            instrument.writeParameter(
                self.PARAM_FLOW_SETPOINT,
                0.0,
            )
            instrument.writeParameter(
                self.PARAM_SETPOINT_RAW,
                0,
            )
        finally:
            self.write_parameter(
                self.PARAM_CONTROL_MODE,
                self.MODE_VALVE_CLOSE,
            )

    def set_direct_valve_position(self, percent: float) -> None:
        if not 0.0 <= percent <= 100.0:
            raise ValueError(
                "Valve position must be between 0 and 100 percent."
            )

        raw_setpoint = round(
            percent / 100.0 * self.SETPOINT_FULL_SCALE
        )

        self.write_parameter(
            self.PARAM_CONTROL_MODE,
            self.MODE_VALVE_STEERING,
        )

        self.write_parameter(
            self.PARAM_SETPOINT_RAW,
            raw_setpoint,
        )
