# src/hardware/drivers/pressure_controller.py
from __future__ import annotations

import os
import logging
import time
import threading
from dataclasses import dataclass
from typing import Optional, Any, Dict, Tuple
from ctypes import c_int32, c_double, byref

from src.hardware.drivers.elveflow import (
    OB1_Initialization, 
    OB1_Destructor, 
    OB1_Set_Press, 
    OB1_Get_Press, 
    Elveflow_Calibration_Load
)

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class PressureControllerConfig:
    device: str = "COM10"
    regs: Tuple[int, int, int, int] = (5, 0, 0, 0)
    calib_path: str = "U:\\PelliKAn\\3_Filtration\\4_Config\\OB1_Calib_latest.txt"
    pressure_limit_mbar: float = 2000.0
    autoload_calib: bool = True

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PressureControllerConfig":
        device = str(d.get("device_name", d.get("device", "COM10"))).strip()
        
        # Robuster Parser für die Regler (stellt sicher, dass es exakt 4 ints sind)
        regs_raw = d.get("regulator_types", d.get("regs", (5, 0, 0, 0)))
        if isinstance(regs_raw, (list, tuple)):
            # Auffüllen mit Nullen, falls jemand aus Versehen nur [5] schreibt
            safe_regs = (list(regs_raw) + [0, 0, 0, 0])[:4]
            regs = tuple(int(x) for x in safe_regs)
        else:
            regs = (5, 0, 0, 0)
        
        limit = float(d.get("pressure_limit", d.get("pressure_limit_mbar", 2000.0)))
        autoload = bool(d.get("autoload_calib", True))
        path = str(d.get("calib_path", "")).strip()

        return cls(
            device=device,
            regs=regs, # type: ignore
            pressure_limit_mbar=limit,
            autoload_calib=autoload,
            calib_path=path
        )

class PressureController:
    """
    Thread-sicherer und optimierter Wrapper für den Elveflow OB1 Controller.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.cfg = PressureControllerConfig.from_dict(config)
        self._instr_id = c_int32(-1)
        self._calib = (c_double * 1000)()
        self._connected = False
        self._last_p = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
        
        # 🚀 OPTIMIERUNG 1: Thread-Lock für sichere GUI-Kommunikation
        self._lock = threading.Lock()
        
        # 🚀 OPTIMIERUNG 2: C-Variable wiederverwenden (Memory-Effizienz)
        self._meas_buffer = c_double(0.0)

    def connect(self) -> None:
        with self._lock:
            if self._connected: 
                return
                
            logger.info("PressureController: Connecting to %s with regs %s", self.cfg.device, self.cfg.regs)
            
            res = OB1_Initialization(
                self.cfg.device, 
                self.cfg.regs[0], self.cfg.regs[1], self.cfg.regs[2], self.cfg.regs[3], 
                byref(self._instr_id)
            )

            if res != 0 or self._instr_id.value < 0:
                logger.error("OB1_Initialization failed: error=%d", res)
                raise RuntimeError(f"OB1_Initialization failed: {res}. Check COM-Port!")

            self._connected = True
            logger.info("OB1 Connected successfully. Instr_ID: %d", self._instr_id.value)

            if self.cfg.autoload_calib and self.cfg.calib_path and os.path.isfile(self.cfg.calib_path):
                self._load_calibration()

    def _load_calibration(self) -> None:
        try:
            res = Elveflow_Calibration_Load(self.cfg.calib_path, self._calib, 1000)
            if res == 0:
                logger.info("Calibration file loaded: %s", self.cfg.calib_path)
            else:
                logger.warning("Calibration file load failed with error: %d", res)
        except Exception as e:
            logger.error("Error during calibration load: %s", e)

    def set_pressure_mbar(self, ch: int, mbar: float) -> None:
        if not self._connected: 
            return
        
        val = float(mbar)
        if abs(val) > self.cfg.pressure_limit_mbar:
            logger.warning("Pressure %.1f exceeds limit %.1f! Clipping.", val, self.cfg.pressure_limit_mbar)
            val = self.cfg.pressure_limit_mbar if val > 0 else -self.cfg.pressure_limit_mbar

        with self._lock:
            res = OB1_Set_Press(self._instr_id.value, int(ch), val, self._calib, 1000)
            
        if res != 0 and not (res == 8008 and val == 0.0):
            logger.warning("OB1_Set_Press failed: error=%d ch=%d val=%.1f", res, ch, val)

    def get_pressure_mbar(self, channel: int) -> float:
        if not self._connected:
            return 0.0
        
        ch = int(channel)
        
        # Lokale Variable erzeugen (besser für Thread-Sicherheit als self._meas_buffer)
        val = c_double(0.0)
        
        try:
            # 🚀 WICHTIG: Thread-Lock für das Auslesen aktivieren!
            # Verhindert, dass das Senden (set_press) und Lesen (get_press) kollidieren.
            with self._lock:
                # acq=1 zwingt die Hardware, einen frischen Messwert zu holen
                res = OB1_Get_Press(self._instr_id.value, ch, 1, self._calib, byref(val), 1000)
            
            # Fehlerprüfung: Wenn res != 0, MÜSSEN wir das wissen!
            if res != 0:
                logger.error("OB1_Get_Press schlug fehl auf Kanal %d! Error-Code: %d", ch, res)
                return 0.0
            
            meas = float(val.value)
            
            # Plausibilitätsprüfung
            if -100.0 < meas < 10000.0:
                return meas
            else:
                logger.warning("Unplausibler Wert von OB1 auf Kanal %d gelesen: %f", ch, meas)
                return 0.0
                
        except Exception as e:
            logger.error("OB1 Read Error CH%d: %s", ch, e)
            return 0.0

    def close(self) -> None:
        if not self._connected: return
        
        with self._lock:
            try:
                # Sicherstellen, dass kein Druck mehr anliegt
                OB1_Set_Press(self._instr_id.value, 1, 0.0, self._calib, 1000)
                OB1_Set_Press(self._instr_id.value, 2, 0.0, self._calib, 1000)
                time.sleep(0.1)
                
                OB1_Destructor(self._instr_id.value)
                logger.info("OB1 Connection closed safely.")
            except Exception as e:
                logger.error("Error during OB1 disconnect: %s", e)
            finally:
                self._connected = False

    # --- Legacy Aliases ---
    def set_pressure(self, value: float, channel: int):
        self.set_pressure_mbar(channel, value)

    def get_pressure(self, channel: int) -> float:
        return self.get_pressure_mbar(channel)