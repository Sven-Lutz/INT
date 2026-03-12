# src/backend/core/device_manager.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Hardware imports (müssen mit deiner Projektstruktur übereinstimmen)
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
    
    # Simulations-Toggle
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

        logger.info(f"DeviceManager: init (pressure={opts.enable_pressure}, flow={opts.enable_flow}, simulate={opts.simulate})")

        if self.opts.simulate:
            logger.info("DeviceManager: Sim mode active. Skipping hardware driver init.")
            return

        # 1. Konfigurationen laden
        valve_cfg = self._load_required_cfg("valves")
        
        pressure_cfg: Optional[Dict[str, Any]] = None
        if opts.enable_pressure:
            pressure_cfg = self._load_required_cfg("pressure_controller")
            
        flow_cfg: Optional[Dict[str, Any]] = None
        if opts.enable_flow:
            flow_cfg = self._load_required_cfg("flow_sensor")

        # 2. Ventile initialisieren
        try:
            self.valve_controller = ValveController(valve_cfg)
            
            # Manche Treiber erfordern ein explizites connect()
            connect_fn = getattr(self.valve_controller, "connect", None)
            if callable(connect_fn):
                connect_fn()
            elif hasattr(self.valve_controller, "relais"):
                rel_connect = getattr(self.valve_controller.relais, "connect", None)
                if callable(rel_connect):
                    rel_connect()

            self._valves_connected = True
            logger.info("DeviceManager: ValveController connected.")
        except Exception as e:
            logger.error(f"DeviceManager: ValveController init failed: {e}")
            if self.opts.require_valves: raise

        # 3. OB1 Druckregler initialisieren
        if opts.enable_pressure:
            assert pressure_cfg is not None, "Pressure config is required but missing."
            try:
                self.pressure_controller = PressureController(pressure_cfg)
                
                # Explizites Connect falls nötig
                connect_fn = getattr(self.pressure_controller, "connect", None)
                if callable(connect_fn):
                    connect_fn()
                    
                logger.info("DeviceManager: PressureController (OB1) connected.")
            except Exception as e:
                logger.error(f"DeviceManager: PressureController init failed: {e}")
                if self.opts.require_pressure: raise
                self.pressure_controller = None

        # 4. Flusssensor initialisieren
        if opts.enable_flow:
            assert flow_cfg is not None, "Flow config is required but missing."
            try:
                self.flow_sensor = FlowSensor(flow_cfg)
                
                # Hier rufen wir explizit connect() auf, wie in der FlowSensor Klasse definiert
                self.flow_sensor.connect()
                
                logger.info("DeviceManager: FlowSensor connected.")
            except Exception as e:
                logger.error(f"DeviceManager: FlowSensor init failed: {e}")
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

    def _load_required_cfg(self, name: str) -> Dict[str, Any]:
        cfg = self.cfg_mgr.load_config(name)
        if not isinstance(cfg, dict): raise ValueError(f"Config '{name}' must be a mapping.")
        return cfg

    # ---------------- Hardware Guards ----------------
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
    # 🚀 ADAPTER: KORREKTE API AUFRUFE FÜR DEINE ALTEN TREIBER
    # =====================================================================

    def set_pressure_setpoint_mbar(self, *, channel: int, setpoint_mbar: float, ramp: bool = True) -> None:
        pc = self._require_pressure()
        
        # 🚀 SUCHT JETZT NACH DEN KORREKTEN NEUEN METHODEN
        for method_name in ("set_pressure_mbar", "set_pressure", "write_pressure"):
            fn: Any = getattr(pc, method_name, None)
            if callable(fn):
                try:
                    # Versucht zuerst die aktuelle Signatur
                    fn(ch=int(channel), value_mbar=float(setpoint_mbar))
                    return
                except TypeError:
                    try:
                        # Versucht die Fallback Signatur (channel, value)
                        fn(channel=int(channel), value=float(setpoint_mbar))
                        return
                    except TypeError:
                        # Positional Arguments
                        fn(int(channel), float(setpoint_mbar))
                        return
                        
        raise RuntimeError("PressureController hat keine bekannte Methode zum Setzen des Drucks.")

    def get_pressure_mbar(self, channel: int) -> float:
        pc = self._require_pressure()
        
        # 🚀 SUCHT JETZT NACH DEN KORREKTEN NEUEN METHODEN
        for method_name in ("get_pressure_mbar", "read_pressure", "get_pressure"):
            fn: Any = getattr(pc, method_name, None)
            if callable(fn):
                try:
                    v: Any = fn(ch=int(channel))
                except TypeError:
                    try:
                        v: Any = fn(channel=int(channel))
                    except TypeError:
                        v: Any = fn(int(channel))
                
                if v is None: 
                    return 0.0 # Safety Fallback
                if hasattr(v, "magnitude"): 
                    return float(v.magnitude)
                return float(v)
                
        raise RuntimeError(f"PressureController hat keine bekannte Methode zum Lesen des Drucks. Verfügbare Attribute: {dir(pc)}")

    def get_pressure_setpoint_mbar(self, channel: int) -> float:
        return self.get_pressure_mbar(channel)

    def read_flow(self) -> float:
        fs = self._require_flow()
        fn: Any = getattr(fs, "get_flow", None)
        
        if callable(fn):
            v: Any = fn()
            if v is None: 
                return 0.0
            if hasattr(v, "magnitude"): 
                return float(v.magnitude)
            return float(v)
            
        raise RuntimeError("FlowSensor hat keine get_flow Methode.")

    def set_valve_state(self, state: str) -> None:
        vc = self._require_valves()
        st = str(state).strip().upper()

        state_map = {
            self.STATE_FILTRATION: "filtration",
            self.STATE_FILLING: "filling_solution",
            self.STATE_VENTING: "venting",
            # WICHTIG: Dein alter Treiber nutzt "backwashing", nicht "backwash"!
            self.STATE_BACKWASH: "backwashing", 
            self.STATE_SHUT: "all_shut",
            self.STATE_OPEN: "all_open"
        }
        
        mapped_fn = state_map.get(st, "venting")
        fn: Any = getattr(vc, mapped_fn, None)
        
        if callable(fn):
            fn()
        else:
            raise ValueError(f"Unknown valve state '{state}' (mapped to {mapped_fn})")

    def get_valve_state(self) -> str:
        vc = self._require_valves()
        if hasattr(vc, "state") and isinstance(vc.state, dict):
            return str(vc.state)
        return "UNKNOWN"

    def valves_venting(self) -> None: 
        self.set_valve_state(self.STATE_VENTING)

    def vent_all(self) -> None:
        try: self.valves_venting()
        except Exception: pass
        
        if self.pressure_controller is not None:
            for ch in (1, 2):
                try: self.set_pressure_setpoint_mbar(channel=ch, setpoint_mbar=0.0)
                except Exception: pass

    def disconnect(self) -> None:
        logger.info("DeviceManager: Disconnecting hardware...")
        
        if self.flow_sensor is not None:
            fn: Any = getattr(self.flow_sensor, "close", None)
            if callable(fn): fn()
            self.flow_sensor = None

        if self.pressure_controller is not None:
            for ch in (1, 2):
                try: self.set_pressure_setpoint_mbar(channel=ch, setpoint_mbar=0.0)
                except Exception: pass
            
            fn: Any = getattr(self.pressure_controller, "close", getattr(self.pressure_controller, "shutdown", None))
            if callable(fn): fn()
            self.pressure_controller = None

        if self._valves_connected:
            try:
                if self.opts.safe_valves_on_disconnect:
                    fn: Any = getattr(self.valve_controller, "disconnect", None)
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