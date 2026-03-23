# scripts/calibrate_ob1.py
from __future__ import annotations

import os
from ctypes import c_int32, c_double, byref
from pathlib import Path

# Import der stabilen Wrapper
from src.hardware.drivers.elveflow import (
    OB1_Initialization,
    OB1_Destructor,
    OB1_Set_Press,
    OB1_Get_Press,
    OB1_Calib,
    Elveflow_Calibration_Save,
)

# 🚀 FIX: COM10 statt ASRL10::INSTR (Konsistenz zur App)
DEVICE = "COM10" 
REGS = (5, 0, 0, 0)

TIMEOUT_CALIB_MS = 60000
OUT_PATH = r"C:\Users\Operator\PelliKAn\3_Filtration\4_Config\Calibration\OB1_Calib_latest.txt"

def _readback(instr_id: int, ch: int, calib) -> None:
    out = c_double(0.0)
    # Nutzt jetzt den Wrapper aus elveflow.py (kein byref(calib) hier nötig!)
    e = OB1_Get_Press(instr_id, ch, 1, calib, byref(out))
    if e == 0:
        print(f"    ch{ch} readback = {out.value:.2f} mbar")
    else:
        print(f"    WARN: OB1_Get_Press ch{ch} -> err={e}")

def main() -> None:
    out = Path(OUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)

    instr = c_int32(-1)
    calib = (c_double * 1000)()

    print(f"[1] OB1_Initialization({DEVICE}) mit Reglern {REGS}...")
    # WICHTIG: byref(instr) ist nötig, da Initialization die ID SCHREIBT
    err = OB1_Initialization(DEVICE, *REGS, byref(instr))
    
    if err != 0 or instr.value < 0:
        print(f"❌ FEHLER: Initialisierung fehlgeschlagen (Code {err}).")
        print("Checkliste: Ist ein anderes Programm (ESI, App) offen? Kabel fest?")
        return

    try:
        print(f"[2] Verbunden! ID={instr.value}. Kanäle auf 0 mbar...")
        for ch in (1, 2, 3, 4):
            OB1_Set_Press(instr.value, ch, 0.0, calib)

        print("[3] Starte OB1_Calib (Dauer ca. 60s)...")
        print("👉 BITTE PRÜFEN: Alle Ausgänge müssen mit Stopfen verschlossen sein!")
        
        ecal = OB1_Calib(instr.value, calib, TIMEOUT_CALIB_MS)

        if ecal != 0:
            print(f"❌ Kalibrierung fehlgeschlagen (Error {ecal}).")
            return

        print(f"[4] Speichere neue Kalibrierung nach: {out}")
        esave = Elveflow_Calibration_Save(str(out), calib, 1000)
        
        if esave != 0:
            print(f"❌ Fehler beim Speichern (Error {esave}).")
        else:
            print("✅ [OK] Kalibrierung erfolgreich abgeschlossen und gespeichert.")

    finally:
        print("[5] Schließe Verbindung...")
        try:
            OB1_Destructor(instr.value)
        except:
            pass

if __name__ == "__main__":
    main()