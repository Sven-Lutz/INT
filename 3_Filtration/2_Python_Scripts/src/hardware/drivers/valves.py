# hardware/drivers/valves.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import serial

logger = logging.getLogger(__name__)


class ValveMode(str, Enum):
    FILTRATION = "FILTRATION"
    FILLING = "FILLING"
    VENTING = "VENTING"
    BACKWASH = "BACKWASH"
    ALL_SHUT = "ALL_SHUT"
    ALL_OPEN = "ALL_OPEN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RelayConfig:
    serial_path: str = "COM6"
    baud_rate: int = 9600


class RelayController:
    """
    Minimal controller for a 2-relay module with single-byte commands.
    Assumption (confirmed by you): RELAY ON == VALVE OPEN.
    """
    def __init__(self, serial_path: str = "COM6", baud_rate: int = 9600):
        self.serial_path = str(serial_path).strip() or "COM6"
        self.baud_rate = int(baud_rate)

        # rly02 command mapping
        self.commands = {
            "relay_1_on": 0x65,
            "relay_1_off": 0x6F,
            "relay_2_on": 0x66,
            "relay_2_off": 0x70,
            "info": 0x5A,
            "relay_states": 0x5B,
        }

    def _send_command(self, cmd: int, *, read_response: bool = False) -> Optional[bytes]:
        ser = serial.Serial(self.serial_path, self.baud_rate, timeout=1)
        try:
            ser.write(bytes([cmd]))
            return ser.read(1) if read_response else None
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def turn_relay_1_on(self) -> None:
        self._send_command(self.commands["relay_1_on"])

    def turn_relay_1_off(self) -> None:
        self._send_command(self.commands["relay_1_off"])

    def turn_relay_2_on(self) -> None:
        self._send_command(self.commands["relay_2_on"])

    def turn_relay_2_off(self) -> None:
        self._send_command(self.commands["relay_2_off"])


class ValveController:
    """
    Valve controller using a 2-relay board (rly02-style).

    Confirmed mapping:
      - Relay ON  -> Valve OPEN
      - Relay OFF -> Valve CLOSED

    Modes (per your clarification):
      - BACKWASH = ALL OPEN (both relays ON)
      - ALL_SHUT = all valves CLOSED (both relays OFF)

    NOTE:
      - FILTRATION / FILLING / VENTING depend on your plumbing.
        Defaults below preserve your previous intent as much as possible,
        but you should adjust if the physical behavior differs.
    """

    def __init__(self, config: dict):
        serial_path = (
            config.get("COM Port")
            or config.get("com_port")
            or config.get("port")
            or "COM6"
        )
        baud_rate = int(config.get("Baud Rate") or config.get("baud_rate") or 9600)

        self.relais = RelayController(serial_path=str(serial_path), baud_rate=baud_rate)
        self._state: ValveMode = ValveMode.UNKNOWN

        logger.info(
            "ValveController initialized (port=%s, baud=%s)",
            serial_path,
            baud_rate,
        )

    def _set_relays(self, *, r1_on: bool, r2_on: bool, state: ValveMode) -> None:
        logger.debug("ValveController: set state=%s (R1=%s, R2=%s)", state, r1_on, r2_on)

        if r1_on:
            self.relais.turn_relay_1_on()
        else:
            self.relais.turn_relay_1_off()

        if r2_on:
            self.relais.turn_relay_2_on()
        else:
            self.relais.turn_relay_2_off()

        self._state = state
        logger.info("ValveController: state -> %s", self._state.value)

    def get_state(self) -> str:
        return self._state.value

    def filtration(self) -> None:
        self._set_relays(r1_on=True, r2_on=False, state=ValveMode.FILTRATION)

    def filling_solution(self) -> None:
        self._set_relays(r1_on=False, r2_on=True, state=ValveMode.FILLING)

    def venting(self) -> None:
        self._set_relays(r1_on=False, r2_on=True, state=ValveMode.VENTING)

    def backwash(self) -> None:
        self._set_relays(r1_on=True, r2_on=True, state=ValveMode.BACKWASH)

    def all_shut(self) -> None:
        self._set_relays(r1_on=False, r2_on=False, state=ValveMode.ALL_SHUT)

    def all_open(self) -> None:
        self._set_relays(r1_on=True, r2_on=True, state=ValveMode.ALL_OPEN)

    def disconnect(self) -> None:
        logger.info("ValveController: disconnect -> venting")
        try:
            self.venting()
        except Exception:
            logger.exception("ValveController: disconnect venting failed")
            try:
                self.all_shut()
            except Exception:
                logger.exception("ValveController: disconnect all_shut fallback failed")
