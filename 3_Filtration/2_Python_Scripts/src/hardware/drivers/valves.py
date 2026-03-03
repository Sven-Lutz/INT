# src/hardware/drivers/valves.py
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
    # PATCH: if True, try to lock COM port exclusively (can raise PermissionError if a second instance runs)
    exclusive: bool = False

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

        # PATCH: accept exclusive in config (defaults to False to avoid PermissionError during dev)
        exclusive_raw = d.get("exclusive", d.get("serial_exclusive", False))

        return RelayConfig(
            port=str(port).strip() or "COM6",
            baudrate=int(baud),
            timeout_s=float(timeout_s),
            write_delay_s=float(write_delay_s),
            exclusive=bool(exclusive_raw),
        )


class RelayController:
    """
    Minimal controller for a rly02-style 2-relay module with single-byte commands.

    PATCHES vs previous:
    - optional 'exclusive' lock is configurable (default False to reduce PermissionError surprises)
    - thread-safe-ish: serialize writes with a simple in-instance lock-free guard via connect requirement
      (real threading safety should be handled above this layer)
    - safe reconnect: if port open fails, leave self.serial=None and raise cleanly
    - fewer stale-byte issues: reset_input_buffer before *and* after reads where reasonable
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
            "RelayController: connecting (port=%s baud=%s timeout=%ss exclusive=%s)",
            self.cfg.port,
            self.cfg.baudrate,
            self.cfg.timeout_s,
            self.cfg.exclusive,
        )

        try:
            kwargs = dict(
                timeout=self.cfg.timeout_s,
                write_timeout=self.cfg.timeout_s,
            )

            # On pyserial for Windows, exclusive can prevent multiple opens, but can also cause PermissionError
            if self.cfg.exclusive:
                try:
                    self.serial = serial.Serial(self.cfg.port, self.cfg.baudrate, exclusive=True, **kwargs)  # type: ignore[arg-type]
                except TypeError:
                    # pyserial without 'exclusive' support
                    self.serial = serial.Serial(self.cfg.port, self.cfg.baudrate, **kwargs)
            else:
                self.serial = serial.Serial(self.cfg.port, self.cfg.baudrate, **kwargs)

            # Clear any boot noise / stale bytes
            try:
                self.serial.reset_input_buffer()
                self.serial.reset_output_buffer()
            except Exception:
                pass

        except Exception as e:
            # Ensure we never leave a half-initialized handle around
            self.serial = None
            logger.exception("RelayController: failed to open %s (%s)", self.cfg.port, e)
            raise

    def _require_connected(self) -> None:
        if self.serial is None:
            raise RuntimeError("RelayController not connected. Call connect() first.")

    def _send_command(self, cmd: int, *, read_response: bool = False, n: int = 1) -> Optional[bytes]:
        self._require_connected()
        assert self.serial is not None

        try:
            # Prevent stale bytes from being interpreted as reply
            try:
                self.serial.reset_input_buffer()
            except Exception:
                pass

            self.serial.write(bytes([int(cmd) & 0xFF]))
            try:
                self.serial.flush()
            except Exception:
                pass

            if self.cfg.write_delay_s > 0:
                time.sleep(self.cfg.write_delay_s)

            if not read_response:
                return None

            data = self.serial.read(int(n))

            # Clear trailing bytes (some boards may send more than requested)
            try:
                self.serial.reset_input_buffer()
            except Exception:
                pass

            return data if data else b""
        except Exception:
            logger.exception("RelayController: send command failed (cmd=0x%02X)", cmd)
            raise

    def get_relay_states(self) -> Optional[int]:
        """
        Best-effort read. Many boards return 1 byte bitmask:
          bit0 -> relay1, bit1 -> relay2.
        Returns None if not available.
        """
        try:
            res = self._send_command(self.commands["relay_states"], read_response=True, n=1)
            if not res:
                return None
            return int(res[0])
        except Exception:
            return None

    def turn_relay_1_on(self) -> None:
        self._send_command(self.commands["relay_1_on"])

    def turn_relay_1_off(self) -> None:
        self._send_command(self.commands["relay_1_off"])

    def turn_relay_2_on(self) -> None:
        self._send_command(self.commands["relay_2_on"])

    def turn_relay_2_off(self) -> None:
        self._send_command(self.commands["relay_2_off"])

    def close(self) -> None:
        ser = self.serial
        self.serial = None
        if ser is None:
            return
        try:
            try:
                ser.flush()
            except Exception:
                pass
            ser.close()
        except Exception:
            logger.exception("RelayController: error while closing serial")
        finally:
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

    # explicit backwash mapping
    backwash_r1_on: bool = True
    backwash_r2_on: bool = True

    # optional debounce / write batching
    settle_delay_s: float = 0.0

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

        relay_dict = cfg_src.get("relay")
        if isinstance(relay_dict, dict):
            relay_cfg = RelayConfig.from_dict(relay_dict)
        else:
            relay_cfg = RelayConfig.from_dict(cfg_src)

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
            backwash_r1_on=bool(cfg_src.get("backwash_r1_on", True)),
            backwash_r2_on=bool(cfg_src.get("backwash_r2_on", True)),
            settle_delay_s=float(cfg_src.get("settle_delay_s", 0.0)),
        )


class ValveController:
    """
    Valve controller using a 2-relay board.

    Confirmed mapping:
      - Relay ON  -> Valve OPEN
      - Relay OFF -> Valve CLOSED

    PATCHES vs previous:
    - tracks last relay outputs to avoid unnecessary writes (reduces serial traffic and relay wear)
    - still keeps idempotent state transitions by ValveMode
    """

    def __init__(self, config: Dict[str, Any]):
        self.cfg = ValveControllerConfig.from_dict(config)
        self.relais = RelayController(self.cfg.relay)
        self._state: ValveMode = ValveMode.UNKNOWN

        # PATCH: track last relay outputs (None = unknown)
        self._r1_on: Optional[bool] = None
        self._r2_on: Optional[bool] = None

        logger.info(
            "ValveController initialized (port=%s, baud=%s, safe=%s, exclusive=%s)",
            self.cfg.relay.port,
            self.cfg.relay.baudrate,
            self.cfg.safe_state_on_disconnect.value,
            self.cfg.relay.exclusive,
        )

    def connect(self) -> None:
        self.relais.connect()

    def _apply_relay_1(self, on: bool) -> None:
        if self._r1_on is not None and self._r1_on == bool(on):
            return
        if on:
            self.relais.turn_relay_1_on()
        else:
            self.relais.turn_relay_1_off()
        self._r1_on = bool(on)

    def _apply_relay_2(self, on: bool) -> None:
        if self._r2_on is not None and self._r2_on == bool(on):
            return
        if on:
            self.relais.turn_relay_2_on()
        else:
            self.relais.turn_relay_2_off()
        self._r2_on = bool(on)

    def _set_relays(self, *, r1_on: bool, r2_on: bool, state: ValveMode) -> None:
        # idempotent: avoid spamming serial (also reduces relay wear / EMI)
        if self._state == state:
            return

        logger.debug("ValveController: set state=%s (R1=%s, R2=%s)", state.value, r1_on, r2_on)

        # Deterministic write order
        self._apply_relay_1(bool(r1_on))
        self._apply_relay_2(bool(r2_on))

        if self.cfg.settle_delay_s > 0:
            time.sleep(self.cfg.settle_delay_s)

        self._state = state
        logger.info("ValveController: state -> %s", self._state.value)

    def get_state(self) -> str:
        return self._state.value

    # ---- High-level actions ----

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
        self._set_relays(
            r1_on=self.cfg.backwash_r1_on,
            r2_on=self.cfg.backwash_r2_on,
            state=ValveMode.BACKWASH,
        )

    def all_shut(self) -> None:
        self._set_relays(r1_on=False, r2_on=False, state=ValveMode.ALL_SHUT)

    def all_open(self) -> None:
        self._set_relays(r1_on=True, r2_on=True, state=ValveMode.ALL_OPEN)

    # ---- Unified setter (useful for UI manual controls) ----

    def set_state(self, state: str | ValveMode) -> None:
        """
        Single entry point for external layers (UI/DeviceManager).
        Accepts ValveMode or string (case-insensitive).
        """
        if isinstance(state, ValveMode):
            mode = state
        else:
            s = str(state).strip().upper()
            mode = ValveMode.__members__.get(s, ValveMode.UNKNOWN)

        if mode == ValveMode.FILTRATION:
            self.filtration()
        elif mode == ValveMode.FILLING:
            self.filling_solution()
        elif mode == ValveMode.VENTING:
            self.venting()
        elif mode == ValveMode.BACKWASH:
            self.backwash()
        elif mode == ValveMode.ALL_SHUT:
            self.all_shut()
        elif mode == ValveMode.ALL_OPEN:
            self.all_open()
        else:
            raise ValueError(f"Unknown valve state: {state!r}")

    # ---- Shutdown ----

    def disconnect(self) -> None:
        logger.info("ValveController: disconnect -> safe state %s", self.cfg.safe_state_on_disconnect.value)
        try:
            # Always try to move to safe state first (best effort)
            if self.cfg.safe_state_on_disconnect == ValveMode.ALL_SHUT:
                self.all_shut()
            elif self.cfg.safe_state_on_disconnect == ValveMode.ALL_OPEN:
                self.all_open()
            elif self.cfg.safe_state_on_disconnect == ValveMode.BACKWASH:
                self.backwash()
            elif self.cfg.safe_state_on_disconnect == ValveMode.FILLING:
                self.filling_solution()
            elif self.cfg.safe_state_on_disconnect == ValveMode.FILTRATION:
                self.filtration()
            else:
                self.venting()
        except Exception:
            logger.exception("ValveController: failed to set safe state during disconnect")
        finally:
            try:
                self.relais.close()
            except Exception:
                logger.exception("ValveController: relay close failed")

            # PATCH: clear cached outputs, so a future reconnect writes deterministically
            self._r1_on = None
            self._r2_on = None
            self._state = ValveMode.UNKNOWN

    def close(self) -> None:
        self.disconnect()

    def __enter__(self) -> "ValveController":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
