# src/hardware/drivers/pressure_controller.py
from __future__ import annotations

import os
import logging
import time
import threading
from dataclasses import dataclass
from typing import Any, Dict, Tuple
from ctypes import c_int32, c_double, byref
import pathlib

from src.hardware.drivers.elveflow import (
    OB1_Initialization, 
    OB1_Destructor, 
    OB1_Set_Press, 
    OB1_Get_Data, 
    OB1_Calib_Load
)

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class PressureControllerConfig:
    device: str = "COM10"
    regs: Tuple[int, int, int, int] = (5, 0, 0, 0)
    calib_path: str = ""  # Wird jetzt dynamisch überschrieben
    pressure_limit_mbar: float = 2000.0
    autoload_calib: bool = True

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PressureControllerConfig":
        device = str(d.get("device_name", d.get("device", "COM10"))).strip()
        
        regs_raw = d.get("regulator_types", d.get("regs", (5, 0, 0, 0)))
        if isinstance(regs_raw, (list, tuple)):
            safe_regs = (list(regs_raw) + [0, 0, 0, 0])[:4]
            regs = tuple(int(x) for x in safe_regs)
        else:
            regs = (5, 0, 0, 0)
            
        limit = float(d.get("pressure_limit", d.get("pressure_limit_mbar", 2000.0)))
        autoload = bool(d.get("autoload_calib", True))
        
        # --- ÜBERARBEITET: Robuste Pfadfindung mit Path.cwd() ---
        path_str = str(d.get("calib_path", "")).strip()
        path = pathlib.Path(path_str)
        
        # 1. Prüfen, ob der direkt übergebene Pfad (z.B. U:\...) existiert
        if not path.is_file():
            # 2. Dynamischen Pfad relativ zum Ausführungsverzeichnis (CWD) aufbauen
            # CWD ist hier '2_Python_Scripts'. parent geht hoch zu '3_Filtration'
            base_dir = pathlib.Path.cwd().parent 
            alt_path = base_dir / "4_Config" / "OB1_Calib_latest.txt"
            
            if alt_path.is_file():
                path = alt_path
            else:
                logger.warning(f"WARNUNG: Kalibrierungsdatei weder unter '{path_str}' noch lokal ('{alt_path}') gefunden!")
                path = pathlib.Path("") # Leerer Pfad als Fallback

        # str(path) konvertiert das Path-Objekt zurück in einen String für die C-Bibliothek
        return cls(device=device, regs=regs, pressure_limit_mbar=limit, autoload_calib=autoload, calib_path=str(path)) # type: ignore
    
class PressureController:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.cfg = PressureControllerConfig.from_dict(config)
        self._instr_id = c_int32(-1)
        self._connected = False
        self._lock = threading.Lock()

    def connect(self) -> None:
        with self._lock:
            if self._connected: return
            logger.info("PressureController: Connecting to %s with regs %s", self.cfg.device, self.cfg.regs)
            res = OB1_Initialization(
                self.cfg.device, 
                self.cfg.regs[0], self.cfg.regs[1], self.cfg.regs[2], self.cfg.regs[3], 
                byref(self._instr_id)
            )
            if res != 0 or self._instr_id.value < 0:
                raise RuntimeError(f"OB1_Initialization failed: {res}. Check COM-Port!")

            self._connected = True
            logger.info("OB1 Connected successfully. Instr_ID: %d", self._instr_id.value)

            if self.cfg.autoload_calib and self.cfg.calib_path and os.path.isfile(self.cfg.calib_path):
                self._load_calibration()

    def _load_calibration(self) -> None:
        try:
            # V3 API: Das Gerät lädt die Kalibrierung intern über die ID
            res = OB1_Calib_Load(self._instr_id.value, self.cfg.calib_path)
            if res == 0:
                logger.info("Calibration file loaded: %s", self.cfg.calib_path)
            else:
                logger.warning("Calibration load failed with error: %d", res)
        except Exception as e:
            logger.error("Error during calibration load: %s", e)

    def set_pressure_mbar(self, ch: int, mbar: float) -> None:
        if not self._connected: return
        val = float(mbar)
        if abs(val) > self.cfg.pressure_limit_mbar:
            logger.warning("Pressure %.1f exceeds limit %.1f! Clipping.", val, self.cfg.pressure_limit_mbar)
            val = self.cfg.pressure_limit_mbar if val > 0 else -self.cfg.pressure_limit_mbar

        with self._lock:
            # V3 API: Nur 3 Argumente!
            res = OB1_Set_Press(self._instr_id.value, int(ch), val)
            
        if res != 0 and val != 0.0:
            logger.warning("OB1_Set_Press failed: error=%d ch=%d val=%.1f", res, ch, val)

    def get_pressure_mbar(self, channel: int) -> float:
        if not self._connected: return 0.0
        ch = int(channel)
        data_reg = c_double(0.0)
        data_sens = c_double(0.0)
        
        try:
            with self._lock:
                res = OB1_Get_Data(self._instr_id.value, ch, data_reg, data_sens)
            
            if res != 0:
                # Optional: Error Logging reduzieren, wenn das System busy ist
                # logger.error("OB1_Get_Data schlug fehl auf Kanal %d! Error-Code: %d", ch, res)
                return 0.0
            
            meas = float(data_reg.value)
            if -100.0 < meas < 10000.0:
                return meas
            return 0.0
                
        except Exception as e:
            logger.error("OB1 Read Error CH%d: %s", ch, e)
            return 0.0

    def close(self) -> None:
        if not self._connected: return
        with self._lock:
            try:
                OB1_Set_Press(self._instr_id.value, 1, 0.0)
                OB1_Set_Press(self._instr_id.value, 2, 0.0)
                time.sleep(0.1)
                OB1_Destructor(self._instr_id.value)
                logger.info("OB1 Connection closed safely.")
            except Exception as e:
                logger.error("Error during OB1 disconnect: %s", e)
            finally:
                self._connected = False

    def set_pressure(self, value: float, channel: int):
        self.set_pressure_mbar(channel, value)

    def get_pressure(self, channel: int) -> float:
        return self.get_pressure_mbar(channel)