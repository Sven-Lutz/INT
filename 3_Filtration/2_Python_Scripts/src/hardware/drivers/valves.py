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
    exclusive: bool = False

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RelayConfig":
        port = d.get("COM Port") or d.get("com_port") or d.get("serial_path") or d.get("port") or "COM6"
        baud = d.get("Baud Rate") or d.get("baud_rate") or d.get("baudrate") or 9600
        timeout_s = d.get("timeout_s", 1.0)
        write_delay_s = d.get("write_delay_s", 0.05)
        exclusive_raw = d.get("exclusive", d.get("serial_exclusive", False))

        return RelayConfig(
            port=str(port).strip() or "COM6",
            baudrate=int(baud),
            timeout_s=float(timeout_s),
            write_delay_s=float(write_delay_s),
            exclusive=bool(exclusive_raw),
        )

class RelayController:
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

    def connect(self) -> None:
        if self.serial is not None: return
        logger.info("RelayController: connecting (port=%s baud=%s exclusive=%s)", self.cfg.port, self.cfg.baudrate, self.cfg.exclusive)
        try:
            t = float(self.cfg.timeout_s)
            
            # 🚀 LÖSUNG: Direkte Übergabe der Parameter statt **kwargs (macht Pylance glücklich)
            if self.cfg.exclusive:
                try: 
                    self.serial = serial.Serial(self.cfg.port, self.cfg.baudrate, timeout=t, write_timeout=t, exclusive=True)
                except TypeError: 
                    self.serial = serial.Serial(self.cfg.port, self.cfg.baudrate, timeout=t, write_timeout=t)
            else:
                self.serial = serial.Serial(self.cfg.port, self.cfg.baudrate, timeout=t, write_timeout=t)
                
            try:
                self.serial.reset_input_buffer()
                self.serial.reset_output_buffer()
            except Exception: pass
        except Exception as e:
            self.serial = None
            logger.exception("RelayController: failed to open %s -> %s", self.cfg.port, e)
            raise
        
    def _require_connected(self) -> None:
        if self.serial is None: raise RuntimeError("RelayController not connected.")

    def _send_command(self, cmd: int, *, read_response: bool = False, n: int = 1) -> Optional[bytes]:
        self._require_connected()
        assert self.serial is not None
        try:
            try: self.serial.reset_input_buffer()
            except Exception: pass
            self.serial.write(bytes([int(cmd) & 0xFF]))
            try: self.serial.flush()
            except Exception: pass
            if self.cfg.write_delay_s > 0: time.sleep(self.cfg.write_delay_s)
            if not read_response: return None
            data = self.serial.read(int(n))
            try: self.serial.reset_input_buffer()
            except Exception: pass
            return data if data else b""
        except Exception:
            logger.exception("RelayController: send command failed (cmd=0x%02X)", cmd)
            raise

    def turn_relay_1_on(self) -> None: self._send_command(self.commands["relay_1_on"])
    def turn_relay_1_off(self) -> None: self._send_command(self.commands["relay_1_off"])
    def turn_relay_2_on(self) -> None: self._send_command(self.commands["relay_2_on"])
    def turn_relay_2_off(self) -> None: self._send_command(self.commands["relay_2_off"])

    def close(self) -> None:
        ser = self.serial
        self.serial = None
        if ser is None: return
        try:
            try: ser.flush()
            except Exception: pass
            ser.close()
        except Exception: pass

@dataclass(frozen=True)
class ValveControllerConfig:
    relay: RelayConfig = RelayConfig()
    safe_state_on_disconnect: ValveMode = ValveMode.VENTING

    # 🚀 INVERTIERTE LOGIK FÜR PHYSISCHE SCHLÄUCHE 🚀
    filtration_r1_on: bool = False
    filtration_r2_on: bool = True
    
    filling_r1_on: bool = True
    filling_r2_on: bool = False
    
    venting_r1_on: bool = True
    venting_r2_on: bool = False

    backwash_r1_on: bool = True
    backwash_r2_on: bool = True

    settle_delay_s: float = 0.0

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ValveControllerConfig":
        cfg_src = d.get("valves", d)
        relay_cfg = RelayConfig.from_dict(cfg_src.get("relay", cfg_src))
        safe_mode = ValveMode.__members__.get(str(cfg_src.get("safe_state_on_disconnect", cfg_src.get("safe_state", "VENTING"))).upper(), ValveMode.VENTING)

        return ValveControllerConfig(
            relay=relay_cfg,
            safe_state_on_disconnect=safe_mode,
            # Defaults inverted to match physical setup
            filtration_r1_on=bool(cfg_src.get("filtration_r1_on", True)),
            filtration_r2_on=bool(cfg_src.get("filtration_r2_on", False)),
            filling_r1_on=bool(cfg_src.get("filling_r1_on", True)),
            filling_r2_on=bool(cfg_src.get("filling_r2_on", False)),
            venting_r1_on=bool(cfg_src.get("venting_r1_on", True)),
            venting_r2_on=bool(cfg_src.get("venting_r2_on", False)),
            backwash_r1_on=bool(cfg_src.get("backwash_r1_on", False)),
            backwash_r2_on=bool(cfg_src.get("backwash_r2_on", False)),
            settle_delay_s=float(cfg_src.get("settle_delay_s", 0.0)),
        )

class ValveController:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = ValveControllerConfig.from_dict(config)
        self.relais = RelayController(self.cfg.relay)
        self._state: ValveMode = ValveMode.UNKNOWN
        self._r1_on: Optional[bool] = None
        self._r2_on: Optional[bool] = None

    def connect(self) -> None:
        self.relais.connect()

    def _apply_relay_1(self, on: bool) -> None:
        if self._r1_on == bool(on): return
        if on: self.relais.turn_relay_1_on()
        else: self.relais.turn_relay_1_off()
        self._r1_on = bool(on)

    def _apply_relay_2(self, on: bool) -> None:
        if self._r2_on == bool(on): return
        if on: self.relais.turn_relay_2_on()
        else: self.relais.turn_relay_2_off()
        self._r2_on = bool(on)

    def _set_relays(self, *, r1_on: bool, r2_on: bool, state: ValveMode) -> None:
        if self._state == state: return
        logger.debug("ValveController: set state=%s (R1=%s, R2=%s)", state.value, r1_on, r2_on)
        self._apply_relay_1(bool(r1_on))
        self._apply_relay_2(bool(r2_on))
        if self.cfg.settle_delay_s > 0: time.sleep(self.cfg.settle_delay_s)
        self._state = state

    def get_state(self) -> str: return self._state.value
    def filtration(self) -> None: self._set_relays(r1_on=self.cfg.filtration_r1_on, r2_on=self.cfg.filtration_r2_on, state=ValveMode.FILTRATION)
    def filling_solution(self) -> None: self._set_relays(r1_on=self.cfg.filling_r1_on, r2_on=self.cfg.filling_r2_on, state=ValveMode.FILLING)
    def venting(self) -> None: self._set_relays(r1_on=self.cfg.venting_r1_on, r2_on=self.cfg.venting_r2_on, state=ValveMode.VENTING)
    def backwash(self) -> None: self._set_relays(r1_on=self.cfg.backwash_r1_on, r2_on=self.cfg.backwash_r2_on, state=ValveMode.BACKWASH)
    def all_shut(self) -> None: self._set_relays(r1_on=False, r2_on=False, state=ValveMode.ALL_SHUT)
    def all_open(self) -> None: self._set_relays(r1_on=True, r2_on=True, state=ValveMode.ALL_OPEN)

    def set_state(self, state: str | ValveMode) -> None:
        if isinstance(state, ValveMode): mode = state
        else: mode = ValveMode.__members__.get(str(state).strip().upper(), ValveMode.UNKNOWN)
        if mode == ValveMode.FILTRATION: self.filtration()
        elif mode == ValveMode.FILLING: self.filling_solution()
        elif mode == ValveMode.VENTING: self.venting()
        elif mode == ValveMode.BACKWASH: self.backwash()
        elif mode == ValveMode.ALL_SHUT: self.all_shut()
        elif mode == ValveMode.ALL_OPEN: self.all_open()

    def disconnect(self) -> None:
        try:
            if self.cfg.safe_state_on_disconnect == ValveMode.ALL_SHUT: self.all_shut()
            elif self.cfg.safe_state_on_disconnect == ValveMode.ALL_OPEN: self.all_open()
            elif self.cfg.safe_state_on_disconnect == ValveMode.BACKWASH: self.backwash()
            elif self.cfg.safe_state_on_disconnect == ValveMode.FILLING: self.filling_solution()
            elif self.cfg.safe_state_on_disconnect == ValveMode.FILTRATION: self.filtration()
            else: self.venting()
        except Exception: pass
        finally:
            try: self.relais.close()
            except Exception: pass
            self._r1_on = self._r2_on = None
            self._state = ValveMode.UNKNOWN

    def close(self) -> None: self.disconnect()
    def __enter__(self) -> "ValveController": self.connect(); return self
    def __exit__(self, exc_type, exc, tb) -> None: self.close()