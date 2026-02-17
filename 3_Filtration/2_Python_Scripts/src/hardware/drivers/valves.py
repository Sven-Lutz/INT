# hardware/drivers/valves.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

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
    port: str = "COM6"
    baudrate: int = 9600
    timeout_s: float = 1.0
    write_delay_s: float = 0.05

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RelayConfig":
        port = (
            d.get("COM Port")
            or d.get("com_port")
            or d.get("serial_path")
            or d.get("port")
            or "COM6"
        )
        baud = d.get("Baud Rate") or d.get("baud_rate") or d.get("baudrate") or 9600
        timeout_s = d.get("timeout_s", 1.0)
        write_delay_s = d.get("write_delay_s", 0.05)
        return RelayConfig(
            port=str(port),
            baudrate=int(baud),
            timeout_s=float(timeout_s),
            write_delay_s=float(write_delay_s),
        )


class RelayController:
    """
    Minimal controller for a rly02-style 2-relay module with single-byte commands.
    Assumption: RELAY ON == VALVE OPEN.
    """

    def __init__(self, cfg: RelayConfig):
        self.cfg = cfg
        self.serial: Optional[serial.Serial] = None

        self.commands = {
            "relay_1_on": 0x65,
            "relay_1_off": 0x6F,
            "relay_2_on": 0x66,
            "relay_2_off": 0x70,
            "info": 0x5A,
            "relay_states": 0x5B,
        }

        if not str(self.cfg.port).strip():
            raise ValueError("RelayConfig.port must be set.")
        if self.cfg.baudrate <= 0:
            raise ValueError("RelayConfig.baudrate must be > 0.")
        if self.cfg.timeout_s <= 0:
            raise ValueError("RelayConfig.timeout_s must be > 0.")

    def connect(self) -> None:
        if self.serial is not None:
            return
        logger.info(
            "RelayController: connecting (port=%s baud=%s)",
            self.cfg.port,
            self.cfg.baudrate,
        )
        self.serial = serial.Serial(self.cfg.port, self.cfg.baudrate, timeout=self.cfg.timeout_s)

    def _require_connected(self) -> None:
        if self.serial is None:
            raise RuntimeError("RelayController not connected. Call connect() first.")

    def _send_command(self, cmd: int, *, read_response: bool = False) -> Optional[bytes]:
        self._require_connected()
        assert self.serial is not None
        try:
            self.serial.write(bytes([int(cmd) & 0xFF]))
            if self.cfg.write_delay_s > 0:
                time.sleep(self.cfg.write_delay_s)
            return self.serial.read(1) if read_response else None
        except Exception:
            logger.exception("RelayController: send command failed (cmd=0x%02X)", cmd)
            raise

    def turn_relay_1_on(self) -> None:
        self._send_command(self.commands["relay_1_on"])

    def turn_relay_1_off(self) -> None:
        self._send_command(self.commands["relay_1_off"])

    def turn_relay_2_on(self) -> None:
        self._send_command(self.commands["relay_2_on"])

    def turn_relay_2_off(self) -> None:
        self._send_command(self.commands["relay_2_off"])

    def close(self) -> None:
        if self.serial is None:
            return
        try:
            self.serial.close()
        except Exception:
            logger.exception("RelayController: error while closing serial")
        finally:
            self.serial = None
            logger.info("RelayController: disconnected")


@dataclass(frozen=True)
class ValveControllerConfig:
    relay: RelayConfig = RelayConfig()
    safe_state_on_disconnect: ValveMode = ValveMode.VENTING

    # Plumbing-dependent mapping
    filtration_r1_on: bool = True
    filtration_r2_on: bool = False
    filling_r1_on: bool = False
    filling_r2_on: bool = True
    venting_r1_on: bool = False
    venting_r2_on: bool = True

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ValveControllerConfig":
        """
        Supports:
          - legacy flat configs: {"COM Port": "...", "Baud Rate": ...}
          - nested configs: {"valves": {"port": "...", "baudrate": ... , "safe_state": "VENTING", ...}}
          - optional nested relay section: {"relay": {...}} or {"valves": {"relay": {...}}}
        """
        cfg_src: Dict[str, Any] = d
        nested = d.get("valves")
        if isinstance(nested, dict):
            cfg_src = nested

        # allow both flat configs and nested "relay:"
        relay_dict = cfg_src.get("relay")
        if isinstance(relay_dict, dict):
            relay_cfg = RelayConfig.from_dict(relay_dict)
        else:
            relay_cfg = RelayConfig.from_dict(cfg_src)

        # accept aliases: safe_state_on_disconnect OR safe_state
        safe_raw = cfg_src.get("safe_state_on_disconnect", cfg_src.get("safe_state", "VENTING"))
        safe = str(safe_raw).upper()
        safe_mode = ValveMode.__members__.get(safe, ValveMode.VENTING)

        return ValveControllerConfig(
            relay=relay_cfg,
            safe_state_on_disconnect=safe_mode,
            filtration_r1_on=bool(cfg_src.get("filtration_r1_on", True)),
            filtration_r2_on=bool(cfg_src.get("filtration_r2_on", False)),
            filling_r1_on=bool(cfg_src.get("filling_r1_on", False)),
            filling_r2_on=bool(cfg_src.get("filling_r2_on", True)),
            venting_r1_on=bool(cfg_src.get("venting_r1_on", False)),
            venting_r2_on=bool(cfg_src.get("venting_r2_on", True)),
        )


class ValveController:
    """
    Valve controller using a 2-relay board.

    Confirmed mapping:
      - Relay ON  -> Valve OPEN
      - Relay OFF -> Valve CLOSED
    """

    def __init__(self, config: Dict[str, Any]):
        self.cfg = ValveControllerConfig.from_dict(config)
        self.relais = RelayController(self.cfg.relay)
        self._state: ValveMode = ValveMode.UNKNOWN

        logger.info(
            "ValveController initialized (port=%s, baud=%s, safe=%s)",
            self.cfg.relay.port,
            self.cfg.relay.baudrate,
            self.cfg.safe_state_on_disconnect.value,
        )

    def connect(self) -> None:
        self.relais.connect()

    def _set_relays(self, *, r1_on: bool, r2_on: bool, state: ValveMode) -> None:
        logger.debug("ValveController: set state=%s (R1=%s, R2=%s)", state.value, r1_on, r2_on)

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
        self._set_relays(
            r1_on=self.cfg.filtration_r1_on,
            r2_on=self.cfg.filtration_r2_on,
            state=ValveMode.FILTRATION,
        )

    def filling_solution(self) -> None:
        self._set_relays(
            r1_on=self.cfg.filling_r1_on,
            r2_on=self.cfg.filling_r2_on,
            state=ValveMode.FILLING,
        )

    def venting(self) -> None:
        self._set_relays(
            r1_on=self.cfg.venting_r1_on,
            r2_on=self.cfg.venting_r2_on,
            state=ValveMode.VENTING,
        )

    def backwash(self) -> None:
        self._set_relays(r1_on=True, r2_on=True, state=ValveMode.BACKWASH)

    def all_shut(self) -> None:
        self._set_relays(r1_on=False, r2_on=False, state=ValveMode.ALL_SHUT)

    def all_open(self) -> None:
        self._set_relays(r1_on=True, r2_on=True, state=ValveMode.ALL_OPEN)

    def disconnect(self) -> None:
        logger.info("ValveController: disconnect -> safe state %s", self.cfg.safe_state_on_disconnect.value)
        try:
            if self.cfg.safe_state_on_disconnect == ValveMode.ALL_SHUT:
                self.all_shut()
            elif self.cfg.safe_state_on_disconnect == ValveMode.ALL_OPEN:
                self.all_open()
            elif self.cfg.safe_state_on_disconnect == ValveMode.BACKWASH:
                self.backwash()
            else:
                self.venting()
        except Exception:
            logger.exception("ValveController: failed to set safe state during disconnect")
        finally:
            try:
                self.relais.close()
            except Exception:
                logger.exception("ValveController: relay close failed")

    def close(self) -> None:
        self.disconnect()

    def __enter__(self) -> "ValveController":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
