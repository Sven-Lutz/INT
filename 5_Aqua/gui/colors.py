from __future__ import annotations

from control.empty_detection import CapacitanceState
from control.state_machine import ProcessState


# Colour is used only where it carries information. Everything else
# keeps the native Qt look.

NEUTRAL = "#6B7280"
OK = "#15803D"
BUSY = "#B45309"
ALERT = "#B91C1C"
INFO = "#0369A1"
LED_ON = "#CA8A04"


_STATE_COLORS: dict[ProcessState, str] = {
    ProcessState.DISCONNECTED: NEUTRAL,
    ProcessState.READY: INFO,
    ProcessState.RUNNING: OK,
    ProcessState.STOPPING: BUSY,
    ProcessState.STOPPED: NEUTRAL,
    ProcessState.FAULT: ALERT,
}


_CAPACITANCE_COLORS: dict[str, str] = {
    # Water present.
    CapacitanceState.FILLED.value: INFO,
    CapacitanceState.DRAINING.value: BUSY,
    # Empty is the goal of a drain run, not a problem.
    CapacitanceState.EMPTY.value: OK,
    CapacitanceState.UNKNOWN.value: NEUTRAL,
}


_LEVEL_COLORS: dict[str, str] = {
    "INFO": "",
    "SUCCESS": OK,
    "WARNING": BUSY,
    "ERROR": ALERT,
    "DEBUG": NEUTRAL,
}


def process_state_color(state: ProcessState) -> str:
    return _STATE_COLORS.get(state, NEUTRAL)


def capacitance_state_color(state_name: str) -> str:
    return _CAPACITANCE_COLORS.get(state_name, NEUTRAL)


def log_level_color(level: str) -> str:
    return _LEVEL_COLORS.get(level.upper(), "")


def alarm_color(alarm_info: int) -> str:
    return OK if alarm_info == 0 else ALERT


def bold_color_style(color: str) -> str:
    if not color:
        return "font-weight: bold;"
    return f"color: {color}; font-weight: bold;"
