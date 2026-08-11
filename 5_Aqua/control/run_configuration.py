from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config import (
    CAPACITANCE_EMPTY_STOP_ENABLED,
    CAPACITANCE_EMPTY_THRESHOLD,
    DEFAULT_FLOW_SETPOINT_ML_MIN,
    DEFAULT_TARGET_VOLUME_ML,
    DEFAULT_VALVE_POSITION_PERCENT,
    TARGET_VOLUME_STOP_ENABLED,
)


class ControlMode(str, Enum):
    """Exactly one active method for controlling liquid drainage."""

    VALVE_POSITION = "VALVE_POSITION"
    FLOW_TARGET = "FLOW_TARGET"


@dataclass(frozen=True)
class RunConfiguration:
    """Run control and independent stop conditions."""

    control_mode: ControlMode = ControlMode.VALVE_POSITION
    valve_position_percent: float = DEFAULT_VALVE_POSITION_PERCENT
    flow_target_ml_min: float = DEFAULT_FLOW_SETPOINT_ML_MIN
    empty_stop_enabled: bool = CAPACITANCE_EMPTY_STOP_ENABLED
    empty_threshold: float = CAPACITANCE_EMPTY_THRESHOLD
    target_volume_enabled: bool = TARGET_VOLUME_STOP_ENABLED
    target_volume_ml: float = DEFAULT_TARGET_VOLUME_ML

    def __post_init__(self) -> None:
        if not isinstance(self.control_mode, ControlMode):
            try:
                object.__setattr__(
                    self,
                    "control_mode",
                    ControlMode(self.control_mode),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Unknown control mode: {self.control_mode!r}."
                ) from exc

        if not 0.0 <= self.valve_position_percent <= 100.0:
            raise ValueError(
                "valve_position_percent must be between 0 and 100."
            )
        if self.flow_target_ml_min < 0.0:
            raise ValueError("flow_target_ml_min must not be negative.")
        if self.empty_threshold < 0.0:
            raise ValueError("empty_threshold must not be negative.")
        if self.target_volume_enabled and self.target_volume_ml <= 0.0:
            raise ValueError(
                "target_volume_ml must be greater than zero when enabled."
            )

    @property
    def active_target(self) -> float:
        if self.control_mode == ControlMode.VALVE_POSITION:
            return self.valve_position_percent
        return self.flow_target_ml_min
