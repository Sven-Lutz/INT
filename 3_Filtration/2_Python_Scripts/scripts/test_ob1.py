import os
import time
from ctypes import byref, c_double
from src.hardware.drivers.pressure_controller import PressureController

def run_test():
    print("--- STARTING ELVEFLOW DIAGNOSTICS ---")
    
    # 1. KUGELSICHERER PFAD (Wir gehen einen Ordner hoch und dann in 4_Config)
    base_dir = os.path.abspath(os.path.join(os.getcwd(), "..", "4_Config"))
    calib_path = os.path.join(base_dir, "OB1_Calib_latest.txt")
    
    print(f"Suche Kalibrierung unter: {calib_path}")
    
    if not os.path.exists(calib_path):
        print("!!! ALARM !!! Datei existiert dort nicht! Bitte überprüfe den Ordner.")
        return

    # 2. KOMMAS ZU PUNKTEN MACHEN (Der Labor-Klassiker)
    try:
        with open(calib_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        fixed_lines = [line.replace(",", ".") for line in lines]
        with open(calib_path, "w", encoding="utf-8") as f:
            f.writelines(fixed_lines)
        print("-> Datei erfolgreich formatiert (Kommas zu Punkten).")
    except Exception as e:
        print(f"-> Fehler beim Formatieren: {e}")

    # 3. CONTROLLER STARTEN
    cfg_dict = {
        "backend": "elveflow",
        "device_name": "COM10",
        "regulator_types": [5, 5, 0, 0],
        "calib_path": calib_path,  # Unser neuer, sicherer Pfad!
        "autoload_calib": True,
        "pressure_limit": 2000.0
    }
    
    pc = PressureController(cfg_dict)
    pc.connect()
    
    # 4. DER KALIBRIERUNGS-CHECK
    print("\n--- 1. KALIBRIERUNGS-CHECK ---")
    calib = getattr(pc, '_calib', None)
    if calib:
        print(f"Erste 3 Werte: {calib[0]:.4f}, {calib[1]:.4f}, {calib[2]:.4f}")
        if calib[0] == 0.0 and calib[50] == 0.0:
            print("!!! FEHLER: Das Array ist trotz Ladeversuch voller Nullen!")
        else:
            print("-> ERFOLG! Kalibrierung enthält echte Daten!")
    else:
        print("!!! FEHLER: Kein Array gefunden!")

    # 5. HARDWARE SOLLWERT-TEST
    print("\n--- 2. HARDWARE SOLLWERT-TEST ---")
    print("Sende 50.0 mbar an den Controller...")
    pc.set_pressure_mbar(1, 50.0)
    time.sleep(1.0)
    
    try:
        from src.hardware.drivers.elveflow import OB1_Get_Press
        setpoint = c_double(0.0)
        meas = c_double(0.0)
        
        OB1_Get_Press(pc._instr_id.value, 1, 2, pc._calib, byref(setpoint), 1000)
        OB1_Get_Press(pc._instr_id.value, 1, 1, pc._calib, byref(meas), 1000)
        
        print(f"Hardware meldet Sollwert (Setpoint): {setpoint.value:.3f} mbar")
        print(f"Hardware meldet Istwert (Measured):  {meas.value:.3f} mbar")
        
    except Exception as e:
        print(f"Fehler beim Lesezugriff: {e}")
        
    print("\nSchalte Druck ab...")
    pc.set_pressure_mbar(1, 0.0)
    pc.close()
    print("--- TEST COMPLETE ---")

if __name__ == "__main__":
    run_test()