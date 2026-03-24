# src/hardware/drivers/elveflow.py
from __future__ import annotations

import os
import logging
import pathlib
from dataclasses import dataclass
from typing import Optional, Any

from ctypes import (
    CDLL,
    byref,
    c_int32,
    c_uint16,
    c_double,
    c_char_p,
    POINTER,
)

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ElveflowPaths:
    @staticmethod
    def resolve() -> str:
        target = r"C:\Users\Operator\PelliKAn\3_Filtration\4_Config\DLL64\Elveflow64.dll"
        if os.path.isfile(target):
            return target
        try:
            base = pathlib.Path(__file__).resolve().parents[3] 
            alt_target = base / "vendor" / "elveflow" / "DLL64" / "Elveflow64.dll"
            if alt_target.exists():
                return str(alt_target)
        except Exception:
            pass
        raise FileNotFoundError(f"Elveflow64.dll physisch nicht gefunden!\nPfad prüfen: {target}")

def _as_bytes(x: Any) -> bytes:
    if x is None: return b""
    if isinstance(x, (bytes, bytearray)): return bytes(x)
    return str(x).encode("ascii", errors="ignore")

def _ensure_pointer(obj: Any) -> Any:
    """Stellt sicher, dass das übergebene Objekt eine C-Referenz ist."""
    if obj is None or hasattr(obj, '_obj'):
        return obj
    return byref(obj)

class ElveflowDLL:
    OB1_Initialization: Any = None
    OB1_Set_Press: Any = None
    OB1_Get_Data: Any = None  
    OB1_Calib_Load: Any = None  # NEU: V3 Kalibrierungs-Lader
    OB1_Destructor: Any = None

    def __init__(self, dll_path: Optional[str] = None):
        path = dll_path or ElveflowPaths.resolve()
        self.dll_path = path

        logger.info("ElveflowDLL: loading %s", path)
        try:
            self._dll = CDLL(path)
        except Exception as e:
            logger.error(f"CRITICAL: Failed to load DLL. Error: {e}")
            raise
        self._bind_functions()

    def _bind_functions(self) -> None:
        d = self._dll

        self.OB1_Initialization = getattr(d, "OB1_Initialization", None)
        if self.OB1_Initialization:
            self.OB1_Initialization.argtypes = [c_char_p, c_uint16, c_uint16, c_uint16, c_uint16, POINTER(c_int32)]
            self.OB1_Initialization.restype = c_int32

        self.OB1_Set_Press = getattr(d, "OB1_Set_Press", None)
        if self.OB1_Set_Press:
            # V3 API: Genau 3 Argumente (Kein calib-Array mehr!)
            self.OB1_Set_Press.argtypes = [c_int32, c_int32, c_double]
            self.OB1_Set_Press.restype = c_int32

        self.OB1_Get_Data = getattr(d, "OB1_Get_Data", None)
        if self.OB1_Get_Data:
            self.OB1_Get_Data.argtypes = [c_int32, c_int32, POINTER(c_double), POINTER(c_double)]
            self.OB1_Get_Data.restype = c_int32

        self.OB1_Calib_Load = getattr(d, "OB1_Calib_Load", None)
        if self.OB1_Calib_Load:
            # V3 API: Das Gerät lädt die Kalibrierung direkt in seinen Speicher
            self.OB1_Calib_Load.argtypes = [c_int32, c_char_p]
            self.OB1_Calib_Load.restype = c_int32

        self.OB1_Destructor = getattr(d, "OB1_Destructor", None)
        if self.OB1_Destructor:
            self.OB1_Destructor.argtypes = [c_int32]
            self.OB1_Destructor.restype = c_int32

# -----------------------------
# Module-level singleton
# -----------------------------

_DLL_SINGLETON: Optional[ElveflowDLL] = None

def get_elveflow() -> ElveflowDLL:
    global _DLL_SINGLETON
    if _DLL_SINGLETON is None:
        _DLL_SINGLETON = ElveflowDLL()
    return _DLL_SINGLETON

# -----------------------------
# Public API Wrappers
# -----------------------------

def OB1_Initialization(device: Any, r1: int, r2: int, r3: int, r4: int, id_ptr: Any) -> int:
    func = get_elveflow().OB1_Initialization
    if func is None: return -1
    return int(func(_as_bytes(device), int(r1), int(r2), int(r3), int(r4), _ensure_pointer(id_ptr)))

def OB1_Set_Press(instr_id: int, ch: int, val: float) -> int:
    # Nur noch 3 Argumente!
    func = get_elveflow().OB1_Set_Press
    if func is None: return -1
    return int(func(int(instr_id), int(ch), c_double(float(val))))

def OB1_Get_Data(instr_id: int, ch: int, reg_data: Any, sens_data: Any) -> int:
    func = get_elveflow().OB1_Get_Data
    if func is None: return -1
    return int(func(int(instr_id), int(ch), _ensure_pointer(reg_data), _ensure_pointer(sens_data)))

def OB1_Calib_Load(instr_id: int, path: str) -> int:
    func = get_elveflow().OB1_Calib_Load
    if func is None: return -1
    return int(func(int(instr_id), _as_bytes(path)))

def OB1_Destructor(instr_id: int) -> int:
    func = get_elveflow().OB1_Destructor
    if func is None: return -1
    return int(func(int(instr_id)))

# --- PYLANCE EXPORT FREIGABE ---
# Genau das, was wir im Controller importieren!
__all__ = [
    "OB1_Initialization",
    "OB1_Set_Press",
    "OB1_Get_Data",
    "OB1_Calib_Load",
    "OB1_Destructor",
]