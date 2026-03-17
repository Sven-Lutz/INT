# scripts/calibrate_ob1.py
from __future__ import annotations

from ctypes import c_int32, c_double, byref
from pathlib import Path

from src.hardware.drivers.elveflow import (
    OB1_Initialization,
    OB1_Destructor,
    OB1_Set_Press,
    OB1_Get_Press,
    OB1_Calib,
    Elveflow_Calibration_Save,
)

DEVICE = "ASRL10::INSTR"
REGS = (5, 0, 0, 0)

TIMEOUT_SET_MS = 1500
TIMEOUT_GET_MS = 1500
TIMEOUT_CALIB_MS = 60000
TIMEOUT_SAVE_MS = 8000

VISA_TIMEOUT_ERR = -1073807339

OUT_PATH = r"C:\Users\Operator\PelliKAn\3_Filtration\4_Config\Calibration\OB1_Calib_latest.txt"

# -------------------------------------------


def _readback(instr_id: int, ch: int, calib) -> None:
    out = c_double(0.0)
    e = OB1_Get_Press(instr_id, ch, 1, calib, byref(out), TIMEOUT_GET_MS)
    if e == 0:
        print(f"    ch{ch} readback = {out.value:.2f} mbar")
    else:
        print(f"    WARN: OB1_Get_Press ch{ch} -> err={e}")


def main() -> None:
    out = Path(OUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)

    instr = c_int32(-1)
    calib = (c_double * 1000)()

    print(f"[1] OB1_Initialization({DEVICE}) ...")
    err = OB1_Initialization(DEVICE.encode("ascii"), *REGS, byref(instr))
    if err != 0 or instr.value < 0:
        raise RuntimeError(f"OB1_Initialization failed: err={err}, id={instr.value}")

    try:
        print(f"[2] Connected: id={instr.value}. Setting all channels to 0 mbar (safety) ...")
        for ch in (1, 2, 3, 4):
            e = OB1_Set_Press(instr.value, ch, 0.0, calib, TIMEOUT_SET_MS)
            if e != 0:
                print(f"    WARN: OB1_Set_Press ch{ch} -> err={e}")

        print("[2b] Quick comms check (set 50 mbar on ch1, read back) ...")
        e = OB1_Set_Press(instr.value, 1, 50.0, calib, TIMEOUT_SET_MS)
        if e != 0:
            print(f"    WARN: set 50 mbar failed ch1 -> err={e}")
        _readback(instr.value, 1, calib)
        # back to 0
        OB1_Set_Press(instr.value, 1, 0.0, calib, TIMEOUT_SET_MS)

        print("[3] Running OB1_Calib (outputs must be plugged; pressure/vacuum sources ON) ...")
        ecal = OB1_Calib(instr.value, calib, TIMEOUT_CALIB_MS)

        if ecal == VISA_TIMEOUT_ERR:
            print(f"    WARN: OB1_Calib VISA timeout (err={ecal}). Retrying once ...")
            ecal = OB1_Calib(instr.value, calib, TIMEOUT_CALIB_MS)

        if ecal != 0:
            raise RuntimeError(
                "OB1_Calib failed.\n"
                f"  err={ecal}\n"
                "  Checklist:\n"
                "   - Are all OB1 channel outputs plugged/closed?\n"
                "   - Is the pressure source ON and delivering enough input pressure?\n"
                "   - If using dual regulators: is vacuum source connected/ON?\n"
                "   - Do REGS match the real channel regulator types?\n"
            )

        print(f"[4] Saving calibration to: {out} ...")
        esave = Elveflow_Calibration_Save(str(out).encode("ascii"), calib, TIMEOUT_SAVE_MS)
        if esave != 0:
            raise RuntimeError(f"Elveflow_Calibration_Save failed: err={esave}")

        print("[OK] Calibration saved successfully.")

    finally:
        print("[5] Destructor ...")
        try:
            OB1_Destructor(instr.value)
        except Exception as ex:
            print(f"WARN: OB1_Destructor crashed: {ex}")


if __name__ == "__main__":
    main()


