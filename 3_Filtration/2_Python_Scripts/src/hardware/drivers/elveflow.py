# src/hardware/drivers/elveflow.py
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Optional, Sequence, Any

from ctypes import (
    CDLL,
    cast,
    byref,
    c_int32,
    c_uint16,
    c_double,
    c_char_p,
    POINTER,
)

logger = logging.getLogger(__name__)


# -----------------------------
# Paths
# -----------------------------

@dataclass(frozen=True)
class ElveflowPaths:
    """
    Resolves Elveflow64.dll location.

    Priority:
      1) ENV: ELVEFLOW_DLL_PATH
      2) extra candidates passed in resolve()
      3) common lab paths
      4) current working dir
    """
    candidates: tuple[str, ...] = (
        r"C:\Users\Operator\Filtration\4_Config\DLL64\Elveflow64.dll",
        r"C:\Users\Public\Desktop\Calibration\Elveflow64.dll",
        r"C:\Elveflow\Elveflow64.dll",
        r".\Elveflow64.dll",
    )

    @staticmethod
    def resolve(extra: Optional[Sequence[str]] = None) -> str:
        env = os.environ.get("ELVEFLOW_DLL_PATH", "").strip()
        tried: list[str] = []

        if env:
            tried.append(env)
            if os.path.isfile(env):
                return env

        if extra:
            for p in extra:
                p2 = str(p).strip()
                if not p2:
                    continue
                tried.append(p2)
                if os.path.isfile(p2):
                    return p2

        for p in ElveflowPaths().candidates:
            tried.append(p)
            if os.path.isfile(p):
                return p

        raise FileNotFoundError("Elveflow64.dll not found. Tried:\n  - " + "\n  - ".join(tried))


# -----------------------------
# Robust casting helpers
# -----------------------------

def _as_bytes(x: Any) -> bytes:
    if x is None:
        return b""
    if isinstance(x, (bytes, bytearray)):
        return bytes(x)
    return str(x).encode("ascii", errors="ignore")


def _as_cdouble_ptr(x: Any) -> Any:
    """
    Elveflow expects POINTER(c_double * 1000) for calibration buffer.
    """
    if x is None:
        return x
    try:
        # byref() liefert exakt den Pointer, den die C-Bibliothek braucht
        return byref(x)
    except Exception:
        return x


def _as_int32(x: Any) -> int:
    return int(x)


def _as_double(x: Any) -> float:
    """
    Robust conversion to Python float.
    """
    if x is None:
        return 0.0

    if hasattr(x, "value"):
        try:
            return float(x.value)
        except Exception:
            pass

    if isinstance(x, (bytes, bytearray)):
        x = x.decode("ascii", errors="ignore")

    if isinstance(x, str):
        s = x.strip()
        if s.lower().startswith("c_double(") and s.endswith(")"):
            s = s[len("c_double("):-1].strip()
        return float(s)

    return float(x)


# -----------------------------
# DLL wrapper
# -----------------------------

class ElveflowDLL:
    """
    Thin ctypes binding wrapper for Elveflow64.dll (OB1 subset).
    """

    def __init__(self, dll_path: Optional[str] = None):
        path = dll_path or ElveflowPaths.resolve()
        self.dll_path = path

        logger.info("ElveflowDLL: loading %s", path)
        self._dll = CDLL(path)

        self._bind_functions()

    @property
    def dll(self):
        return self._dll

    def _bind_functions(self) -> None:
        d = self._dll

        # WICHTIG: c_uint16 für die Regler
        self.OB1_Initialization = d.OB1_Initialization
        self.OB1_Initialization.argtypes = [c_char_p, c_uint16, c_uint16, c_uint16, c_uint16, POINTER(c_int32)]
        self.OB1_Initialization.restype = c_int32

        # WICHTIG: Der Array-Typ muss exakt c_double * 1000 sein
        calib_array_type = POINTER(c_double * 1000)

        # --- Elveflow_Calibration_Default
        self.Elveflow_Calibration_Default = getattr(d, "Elveflow_Calibration_Default", None)
        if self.Elveflow_Calibration_Default is not None:
            self.Elveflow_Calibration_Default.argtypes = [calib_array_type, c_int32]
            self.Elveflow_Calibration_Default.restype = c_int32

        # --- OB1_Set_Press
        self.OB1_Set_Press = d.OB1_Set_Press
        self.OB1_Set_Press.argtypes = [c_int32, c_int32, c_double, calib_array_type, c_int32]
        self.OB1_Set_Press.restype = c_int32

        # --- OB1_Get_Press
        self.OB1_Get_Press = d.OB1_Get_Press
        self.OB1_Get_Press.argtypes = [c_int32, c_int32, c_int32, calib_array_type, POINTER(c_double), c_int32]
        self.OB1_Get_Press.restype = c_int32

        # --- OB1_Calib
        self.OB1_Calib = getattr(d, "OB1_Calib", None)
        if self.OB1_Calib is not None:
            self.OB1_Calib.argtypes = [c_int32, calib_array_type, c_int32]
            self.OB1_Calib.restype = c_int32

        # --- Elveflow_Calibration_Load
        self.Elveflow_Calibration_Load = getattr(d, "Elveflow_Calibration_Load", None)
        if self.Elveflow_Calibration_Load is not None:
            self.Elveflow_Calibration_Load.argtypes = [c_char_p, calib_array_type, c_int32]
            self.Elveflow_Calibration_Load.restype = c_int32

        # --- Elveflow_Calibration_Save
        self.Elveflow_Calibration_Save = getattr(d, "Elveflow_Calibration_Save", None)
        if self.Elveflow_Calibration_Save is not None:
            self.Elveflow_Calibration_Save.argtypes = [c_char_p, calib_array_type, c_int32]
            self.Elveflow_Calibration_Save.restype = c_int32

        # --- destructor
        self.OB1_Destructor = getattr(d, "OB1_Destructor", None)
        if self.OB1_Destructor is not None:
            self.OB1_Destructor.argtypes = [c_int32]
            self.OB1_Destructor.restype = c_int32

        # --- remote measurement functions
        self.OB1_Start_Remote_Measurement = getattr(d, "OB1_Start_Remote_Measurement", None)
        if self.OB1_Start_Remote_Measurement is not None:
            self.OB1_Start_Remote_Measurement.argtypes = [c_int32, calib_array_type, c_int32]
            self.OB1_Start_Remote_Measurement.restype = c_int32

        self.OB1_Stop_Remote_Measurement = getattr(d, "OB1_Stop_Remote_Measurement", None)
        if self.OB1_Stop_Remote_Measurement is not None:
            self.OB1_Stop_Remote_Measurement.argtypes = [c_int32]
            self.OB1_Stop_Remote_Measurement.restype = c_int32

        self.OB1_Get_Remote_Data = getattr(d, "OB1_Get_Remote_Data", None)
        if self.OB1_Get_Remote_Data is not None:
            self.OB1_Get_Remote_Data.argtypes = [c_int32, c_int32, POINTER(c_double), POINTER(c_double)]
            self.OB1_Get_Remote_Data.restype = c_int32

        logger.info("ElveflowDLL: bound functions OK")

# -----------------------------
# Module-level singleton + exports
# -----------------------------

_DLL_SINGLETON: Optional[ElveflowDLL] = None

def get_elveflow() -> ElveflowDLL:
    global _DLL_SINGLETON
    if _DLL_SINGLETON is None:
        _DLL_SINGLETON = ElveflowDLL()
    return _DLL_SINGLETON

def _fn(name: str):
    return getattr(get_elveflow(), name)


# -----------------------------
# Public API (robust wrappers)
# -----------------------------

def OB1_Initialization(device: Any, reg1: Any, reg2: Any, reg3: Any, reg4: Any, instr_id_ptr: Any) -> int:
    return int(_fn("OB1_Initialization")(_as_bytes(device), int(reg1), int(reg2), int(reg3), int(reg4), instr_id_ptr))

def Elveflow_Calibration_Default(calib: Any, array_length: Any = 1000) -> int:
    fn = getattr(get_elveflow(), "Elveflow_Calibration_Default", None)
    if fn is None:
        raise AttributeError("Elveflow_Calibration_Default not available in this Elveflow64.dll")
    calib_p = _as_cdouble_ptr(calib)
    return int(fn(calib_p, _as_int32(array_length)))

def OB1_Set_Press(instr_id: Any, ch: Any, value: Any, calib: Any, array_length: Any = 1000) -> int:
    calib_p = _as_cdouble_ptr(calib)
    v = _as_double(value)
    return int(_fn("OB1_Set_Press")(_as_int32(instr_id), _as_int32(ch), c_double(v), calib_p, _as_int32(array_length)))

def OB1_Get_Press(instr_id: Any, ch: Any, acquire: Any, calib: Any, out_ptr: Any, array_length: Any = 1000) -> int:
    calib_p = _as_cdouble_ptr(calib)
    return int(_fn("OB1_Get_Press")(_as_int32(instr_id), _as_int32(ch), _as_int32(acquire), calib_p, out_ptr, _as_int32(array_length)))

def OB1_Calib(instr_id: Any, calib: Any, timeout_ms: Any) -> int:
    fn = getattr(get_elveflow(), "OB1_Calib", None)
    if fn is None:
        raise AttributeError("OB1_Calib not available in this Elveflow64.dll")
    calib_p = _as_cdouble_ptr(calib)
    return int(fn(_as_int32(instr_id), calib_p, _as_int32(timeout_ms)))

def Elveflow_Calibration_Load(path: Any, calib: Any, size: Any) -> int:
    fn = getattr(get_elveflow(), "Elveflow_Calibration_Load", None)
    if fn is None:
        raise AttributeError("Elveflow_Calibration_Load not available in this Elveflow64.dll")
    calib_p = _as_cdouble_ptr(calib)
    return int(fn(_as_bytes(path), calib_p, _as_int32(size)))

def Elveflow_Calibration_Save(path: Any, calib: Any, size: Any) -> int:
    fn = getattr(get_elveflow(), "Elveflow_Calibration_Save", None)
    if fn is None:
        raise AttributeError("Elveflow_Calibration_Save not available in this Elveflow64.dll")
    calib_p = _as_cdouble_ptr(calib)
    return int(fn(_as_bytes(path), calib_p, _as_int32(size)))

def OB1_Destructor(instr_id: Any) -> int:
    fn = getattr(get_elveflow(), "OB1_Destructor", None)
    if fn is None:
        raise AttributeError("OB1_Destructor not available in this Elveflow64.dll")
    return int(fn(_as_int32(instr_id)))

def OB1_Start_Remote_Measurement(instr_id: Any, calib: Any, size: Any = 1000) -> int:
    fn = getattr(get_elveflow(), "OB1_Start_Remote_Measurement", None)
    if fn is None:
        raise AttributeError("OB1_Start_Remote_Measurement not available in this Elveflow64.dll")
    calib_p = _as_cdouble_ptr(calib)
    return int(fn(_as_int32(instr_id), calib_p, _as_int32(size)))

def OB1_Stop_Remote_Measurement(instr_id: Any) -> int:
    fn = getattr(get_elveflow(), "OB1_Stop_Remote_Measurement", None)
    if fn is None:
        raise AttributeError("OB1_Stop_Remote_Measurement not available in this Elveflow64.dll")
    return int(fn(_as_int32(instr_id)))

def OB1_Get_Remote_Data(instr_id: Any, ch: Any, reg_ptr: Any, sens_ptr: Any) -> int:
    fn = getattr(get_elveflow(), "OB1_Get_Remote_Data", None)
    if fn is None:
        raise AttributeError("OB1_Get_Remote_Data not available in this Elveflow64.dll")
    return int(fn(_as_int32(instr_id), _as_int32(ch), reg_ptr, sens_ptr))