# src/backend/core/device_manager.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Hardware imports
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
    require_valves: bool = True
    require_pressure: bool = True
    require_flow: bool = True
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

        if self.opts.simulate:
            return

        valve_cfg = self._load_required_cfg("valves")
        pressure_cfg = self._load_required_cfg("pressure_controller") if opts.enable_pressure else None
        flow_cfg = self._load_required_cfg("flow_sensor") if opts.enable_flow else None

        try:
            self.valve_controller = ValveController(valve_cfg)
            connect_fn = getattr(self.valve_controller, "connect", None)
            if callable(connect_fn): connect_fn()
            elif hasattr(self.valve_controller, "relais"):
                rel_connect = getattr(self.valve_controller.relais, "connect", None)
                if callable(rel_connect): rel_connect()
            self._valves_connected = True
        except Exception as e:
            logger.error(f"DeviceManager: ValveController init failed: {e}")

        if opts.enable_pressure and pressure_cfg is not None:
            try:
                self.pressure_controller = PressureController(pressure_cfg)
                connect_fn = getattr(self.pressure_controller, "connect", None)
                if callable(connect_fn): connect_fn()
            except Exception as e:
                logger.error(f"DeviceManager: PressureController init failed: {e}")

        if opts.enable_flow and flow_cfg is not None:
            try:
                self.flow_sensor = FlowSensor(flow_cfg)
                self.flow_sensor.connect()
            except Exception as e:
                logger.error(f"DeviceManager: FlowSensor init failed: {e}")

    @property
    def comm_ok(self) -> bool:
        if self.opts.simulate: return True
        return True

    def _load_required_cfg(self, name: str) -> Dict[str, Any]:
        return self.cfg_mgr.load_config(name)

    def _require_valves(self) -> Any:
        if not self._valves_connected: raise RuntimeError("ValveController not connected.")
        return self.valve_controller

    def _require_pressure(self) -> PressureController:
        if self.pressure_controller is None: raise RuntimeError("PressureController not connected.")
        return self.pressure_controller

    def _require_flow(self) -> FlowSensor:
        if self.flow_sensor is None: raise RuntimeError("FlowSensor not connected.")
        return self.flow_sensor

    # =====================================================================
    # 🚀 OB1 KANAL-SCHALTER (DRUCKAUSGABE)
    # =====================================================================
    def _get_physical_channel(self, logical_channel: int) -> int:
        """
        Hier legst du fest, welcher Prozess auf welchen Schlauch feuert.
        """
        c = int(logical_channel)
        
        if c == 1:
            # RAMPE / FILTRATION
            return 1  # 1 = Schlauch zur Filtrationszelle
            
        if c == 2:
            # BACKWASH
            return 2  # 2 = Schlauch zur Flasche
            
        return c

    def set_pressure_setpoint_mbar(self, *, channel: int, setpoint_mbar: float, ramp: bool = True) -> None:
        pc = self._require_pressure()
        phys_ch = self._get_physical_channel(channel)
        try:
            pc.set_pressure_mbar(phys_ch, float(setpoint_mbar))
        except Exception: pass

    def get_pressure_mbar(self, channel: int) -> float:
        pc = self._require_pressure()
        phys_ch = self._get_physical_channel(channel)
        try:
            v = pc.get_pressure_mbar(phys_ch)
            return 0.0 if v is None else float(v)
        except Exception: return 0.0

    def get_pressure_setpoint_mbar(self, channel: int) -> float:
        return self.get_pressure_mbar(channel)

    def read_flow(self) -> float:
        fs = self._require_flow()
        try:
            v = fs.get_flow()
            return float(v) if v is not None else 0.0
        except Exception: return 0.0

    def set_valve_state(self, state: str) -> None:
        vc = self._require_valves()
        st = str(state).strip().upper()
        mapping = {
            self.STATE_FILTRATION: "filtration",
            self.STATE_FILLING: "filling_solution",
            self.STATE_VENTING: "venting",
            self.STATE_BACKWASH: "backwashing", 
            self.STATE_SHUT: "all_shut",
            self.STATE_OPEN: "all_open"
        }
        fn_name = mapping.get(st, "venting")
        fn: Any = getattr(vc, fn_name, None)
        if callable(fn): fn()

    def get_valve_state(self) -> str:
        vc = self._require_valves()
        if hasattr(vc, "state") and isinstance(vc.state, dict): return str(vc.state)
        return "UNKNOWN"
    
    # ---------------- Legacy Adapter ----------------
    def valves_filtration(self): self.set_valve_state(self.STATE_FILTRATION)
    def valves_filling_solution(self): self.set_valve_state(self.STATE_FILLING)
    def valves_backwash(self): self.set_valve_state(self.STATE_BACKWASH)
    def valves_venting(self) -> None: self.set_valve_state(self.STATE_VENTING)
    def all_valves_shut(self): self.set_valve_state(self.STATE_SHUT)

    def vent_all(self) -> None:
        try: self.valves_venting()
        except Exception: pass
        if self.pressure_controller is not None:
            for ch in (1, 2):
                try: self.set_pressure_setpoint_mbar(channel=ch, setpoint_mbar=0.0)
                except Exception: pass

    def set_pressure(self, channel: int, pressure: float, ramp: bool = True):
        val = getattr(pressure, "magnitude", pressure)
        self.set_pressure_setpoint_mbar(channel=channel, setpoint_mbar=float(val))
        
    def get_pressure(self, channel: int) -> float: return self.get_pressure_mbar(channel)
    def get_pressure_setpoint(self, channel: int) -> float: return self.get_pressure_mbar(channel)

    def disconnect(self) -> None:
        if self.flow_sensor is not None:
            try: self.flow_sensor.close()
            except Exception: pass
            self.flow_sensor = None

        if self.pressure_controller is not None:
            for ch in (1, 2):
                try: self.set_pressure_setpoint_mbar(channel=ch, setpoint_mbar=0.0)
                except Exception: pass
            try: self.pressure_controller.close()
            except Exception: pass
            self.pressure_controller = None

        if self._valves_connected:
            try:
                if self.opts.safe_valves_on_disconnect:
                    fn: Any = getattr(self.valve_controller, "disconnect", None)
                    if callable(fn): fn()
                    else: self.valves_venting()
            except Exception: pass
            finally: self._valves_connected = False

    def __enter__(self) -> "DeviceManager": return self
    def __exit__(self, exc_type, exc, tb) -> None: self.disconnect()