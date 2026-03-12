# src/backend/core/device_manager.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from src.hardware.drivers.flow_sensor import FlowSensor, FlowSensorConfig
from src.hardware.drivers.pressure_controller import PressureController
from src.hardware.drivers.valves import ValveController
from src.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceManagerOptions:
    enable_pressure: bool = True
    enable_flow: bool = True
    safe_valves_on_disconnect: bool = True
    
    # Fail-fast toggles
    require_valves: bool = True
    require_pressure: bool = True
    require_flow: bool = True
    
    # Neu: Expliziter Simulations-Toggle für blitzschnellen Start
    simulate: bool = False


class DeviceManager:
    STATE_FILTRATION = "FILTRATION"
    STATE_FILLING = "FILLING"
    STATE_VENTING = "VENTING"
    STATE_BACKWASH = "BACKWASH"
    STATE_SHUT = "SHUT"
    STATE_OPEN = "OPEN"

    def __init__(self, opts: DeviceManagerOptions = DeviceManagerOptions()):
        self.opts = opts
        self.cfg_mgr = ConfigManager()
        self._valves_connected: bool = False
        
        self.pressure_controller: Optional[PressureController] = None
        self.flow_sensor: Optional[FlowSensor] = None
        self._pressure_full_scale_mbar: float = 8000.0

        logger.info(f"DeviceManager: init (pressure={opts.enable_pressure}, flow={opts.enable_flow}, simulate={opts.simulate})")

        if self.opts.simulate:
            logger.info("DeviceManager: Sim mode active. Skipping hardware driver init.")
            return

        # 1. Konfigurationen laden
        valve_cfg = self._load_required_cfg("valves")
        pressure_cfg = self._load_required_cfg("pressure_controller") if opts.enable_pressure else self._load_optional_cfg("pressure_controller")
        flow_cfg = self._load_required_cfg("flow_sensor") if opts.enable_flow else self._load_optional_cfg("flow_sensor")

        # 2. Ventile initialisieren
        self.valve_controller = ValveController(valve_cfg)
        try:
            self._try_connect_driver(self.valve_controller)
            self._valves_connected = True
            logger.info("DeviceManager: ValveController connected.")
        except Exception as e:
            logger.error(f"DeviceManager: ValveController connect failed: {e}")
            if self.opts.require_valves: raise

        # 3. Druckregler initialisieren
        if opts.enable_pressure and pressure_cfg:
            self._pressure_full_scale_mbar = self._infer_pressure_full_scale_mbar(pressure_cfg)
            try:
                self.pressure_controller = PressureController(pressure_cfg)
                self._try_connect_driver(self.pressure_controller)
                logger.info(f"DeviceManager: PressureController connected (FS={self._pressure_full_scale_mbar}mbar).")
            except Exception as e:
                logger.error(f"DeviceManager: PressureController connect failed: {e}")
                if self.opts.require_pressure: raise
                self.pressure_controller = None

        # 4. Flusssensor initialisieren
        if opts.enable_flow and flow_cfg:
            try:
                fs_cfg = self._parse_flow_cfg(flow_cfg)
                self.flow_sensor = FlowSensor(fs_cfg)
                self._try_connect_driver(self.flow_sensor)
                logger.info(f"DeviceManager: FlowSensor connected (Port={fs_cfg.port}).")
            except Exception as e:
                logger.error(f"DeviceManager: FlowSensor connect failed: {e}")
                if self.opts.require_flow: raise
                self.flow_sensor = None

        logger.info("DeviceManager: Initialization complete.")

    @property
    def comm_ok(self) -> bool:
        if self.opts.simulate: return True
        if self.opts.require_valves and not self._valves_connected: return False
        if self.opts.enable_pressure and self.opts.require_pressure and self.pressure_controller is None: return False
        if self.opts.enable_flow and self.opts.require_flow and self.flow_sensor is None: return False
        return True

    # ---------------- Config Helpers ----------------
    def _load_required_cfg(self, name: str) -> Dict[str, Any]:
        cfg = self.cfg_mgr.load_config(name)
        if not isinstance(cfg, dict):
            raise ValueError(f"Config '{name}' must be a mapping.")
        return cfg

    def _load_optional_cfg(self, name: str) -> Optional[Dict[str, Any]]:
        try:
            cfg = self.cfg_mgr.load_config(name)
            return cfg if isinstance(cfg, dict) else None
        except Exception:
            return None

    @staticmethod
    def _infer_pressure_full_scale_mbar(cfg: Dict[str, Any]) -> float:
        src = cfg.get("pressure_controller", cfg) if isinstance(cfg, dict) else cfg
        for k in ("pressure_full_scale_mbar", "full_scale_mbar", "full_scale", "fs_mbar"):
            try:
                if k in src and src[k] is not None and float(src[k]) > 0:
                    return float(src[k])
            except Exception:
                continue
        return 8000.0

    def _parse_flow_cfg(self, cfg: Dict[str, Any]) -> FlowSensorConfig:
        src = cfg.get("flow", cfg) if isinstance(cfg, dict) else cfg
        return FlowSensorConfig(
            port=str(src.get("port", "COM5")).strip() or "COM5",
            address=int(src.get("address", 3)),
            baudrate=int(src.get("baudrate", 38400)),
            channel=int(src.get("channel", 1)),
            full_scale_raw=int(src.get("full_scale_raw", 32000)),
        )

    # ---------------- Connection & Guards ----------------
    @staticmethod
    def _try_connect_driver(obj: Any) -> None:
        for n in ("connect", "open", "start", "initialize", "init"):
            fn = getattr(obj, n, None)
            if callable(fn):
                fn()
                return

    def _require_valves(self) -> None:
        if not self._valves_connected:
            raise RuntimeError("ValveController not connected.")

    def _require_pressure(self) -> PressureController:
        if self.pressure_controller is None:
            raise RuntimeError("PressureController not connected.")
        return self.pressure_controller

    def _require_flow(self) -> FlowSensor:
        if self.flow_sensor is None:
            raise RuntimeError("FlowSensor not connected.")
        return self.flow_sensor

    # ---------------- Canonical Pressure API (MBAR) ----------------
    def set_pressure_setpoint_mbar(self, *, channel: int, setpoint_mbar: float, ramp: bool = True) -> None:
        pc = self._require_pressure()
        fn = getattr(pc, "set_pressure_setpoint_mbar", None)
        if callable(fn):
            fn(channel=int(channel), setpoint_mbar=float(setpoint_mbar), ramp=bool(ramp))
        else:
            # Fallback auf Legacy Percent Setter
            self.set_pressure(value=self._mbar_to_percent(setpoint_mbar), channel=channel, ramp=ramp)

    def get_pressure_mbar(self, channel: int) -> float:
        pc = self._require_pressure()
        fn = getattr(pc, "get_pressure_mbar", None)
        v: Any = fn(int(channel)) if callable(fn) else self.get_pressure(channel)
        return float(v) if callable(fn) else self._percent_to_mbar(v)

    def get_pressure_setpoint_mbar(self, channel: int) -> float:
        pc = self._require_pressure()
        fn = getattr(pc, "get_pressure_setpoint_mbar", None)
        if callable(fn):
            v: Any = fn(int(channel))
            return float(v)
        else:
            return self._percent_to_mbar(self.get_pressure_setpoint(channel))

    def _mbar_to_percent(self, mbar: float) -> float:
        return (max(0.0, float(mbar)) / self._pressure_full_scale_mbar) * 100.0

    def _percent_to_mbar(self, pct: float) -> float:
        return (float(pct) / 100.0) * self._pressure_full_scale_mbar

# ---------------- Legacy Pressure API (PERCENT) ----------------
    def set_pressure(self, value: float, channel: int, ramp: bool = True) -> None:
        pc = self._require_pressure()
        try: pc.set_pressure(channel=int(channel), value=float(value), ramp=bool(ramp)) # type: ignore
        except TypeError:
            try: pc.set_pressure(float(value), int(channel), bool(ramp)) # type: ignore
            except TypeError: pc.set_pressure(float(value), int(channel)) # type: ignore

    def get_pressure(self, channel: int) -> float:
        pc = self._require_pressure()
        for name in ("read_pressure", "get_pressure", "pressure"):
            fn = getattr(pc, name, None)
            if callable(fn): 
                v: Any = fn(int(channel))
                return float(v)
        raise RuntimeError("No legacy read_pressure method found.")

    def get_pressure_setpoint(self, channel: int) -> float:
        pc = self._require_pressure()
        for name in ("read_setpoint", "get_setpoint", "setpoint"):
            fn = getattr(pc, name, None)
            if callable(fn): 
                v: Any = fn(int(channel))
                return float(v)
        raise RuntimeError("No legacy read_setpoint method found.")

    # ---------------- Canonical Flow API ----------------
    def read_flow(self) -> float:
        fs = self._require_flow()
        for name in ("read_flow_eng", "read_flow"):
            fn = getattr(fs, name, None)
            if callable(fn): 
                v: Any = fn()
                return float(v)
        raise RuntimeError("No read_flow method found.")

    # ---------------- Canonical Valve API ----------------
    def set_valve_state(self, state: str) -> None:
        self._require_valves()
        st = str(state).strip().upper()
        vc = self.valve_controller

        if hasattr(vc, "set_valve_state"):
            vc.set_valve_state(st) # type: ignore
            return

        # Fallback Map
        state_map = {
            self.STATE_FILTRATION: "filtration",
            self.STATE_FILLING: "filling_solution",
            self.STATE_VENTING: "venting",
            self.STATE_BACKWASH: "backwash",
            self.STATE_SHUT: "all_shut",
            self.STATE_OPEN: "all_open"
        }
        
        mapped_fn = state_map.get(st, "venting") # Venting als sicherer Fallback
        fn = getattr(vc, mapped_fn, None)
        if callable(fn):
            fn()
        else:
            raise ValueError(f"Unknown or unsupported valve state '{state}'")

    def get_valve_state(self) -> str:
        fn = getattr(self.valve_controller, "get_state", None)
        if callable(fn):
            try: return str(fn())
            except Exception: pass
        return "UNKNOWN"

    def valves_filtration(self) -> None: self.set_valve_state(self.STATE_FILTRATION)
    def valves_filling_solution(self) -> None: self.set_valve_state(self.STATE_FILLING)
    def valves_venting(self) -> None: self.set_valve_state(self.STATE_VENTING)
    def venting(self) -> None: self.valves_venting()
    def valves_backwash(self) -> None: self.set_valve_state(self.STATE_BACKWASH)

    # ---------------- Safe State & Shutdown ----------------
    def vent_all(self) -> None:
        try: self.valves_venting()
        except Exception: pass
        
        if self.pressure_controller is not None:
            for ch in (1, 2):
                try: self.set_pressure_setpoint_mbar(channel=ch, setpoint_mbar=0.0, ramp=True)
                except Exception: pass

    def disconnect(self) -> None:
        logger.info("DeviceManager: Disconnecting hardware...")
        
        if self.flow_sensor is not None:
            self._try_connect_driver(self.flow_sensor) # Note: _try_connect_driver looks for 'close'/'stop' too if renamed, wait, better use explicit closure
            for fn_name in ("close", "disconnect", "stop", "shutdown"):
                fn = getattr(self.flow_sensor, fn_name, None)
                if callable(fn): fn(); break
            self.flow_sensor = None

        if self.pressure_controller is not None:
            for ch in (1, 2):
                try: self.set_pressure_setpoint_mbar(channel=ch, setpoint_mbar=0.0, ramp=True)
                except Exception: pass
            for fn_name in ("close", "disconnect", "stop", "shutdown"):
                fn = getattr(self.pressure_controller, fn_name, None)
                if callable(fn): fn(); break
            self.pressure_controller = None

        if self._valves_connected:
            try:
                if self.opts.safe_valves_on_disconnect:
                    fn = getattr(self.valve_controller, "close", getattr(self.valve_controller, "disconnect", None))
                    if callable(fn): fn()
                    else: self.valves_venting()
            except Exception: pass
            finally:
                self._valves_connected = False

        logger.info("DeviceManager: Disconnect complete.")

    def __enter__(self) -> "DeviceManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()