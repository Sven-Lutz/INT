import time
from ctypes import byref, c_double
from src.hardware.drivers.pressure_controller import PressureController

def run_test():
    print("--- STARTING ELVEFLOW DIAGNOSTICS ---")
    
    cfg_dict = {
        "backend": "elveflow",
        "device_name": "COM10",
        "regulator_types": [5, 5, 0, 0],
        "calib_path": "U:\\PelliKAn\\3_Filtration\\4_Config\\OB1_Calib_latest.txt",
        "autoload_calib": True,
        "pressure_limit": 2000.0
    }
    
    pc = PressureController(cfg_dict)
    pc.connect()
    
    # 1. DER KALIBRIERUNGS-BEWEIS
    print("\n--- 1. KALIBRIERUNGS-CHECK ---")
    try:
        calib = pc._calib
        print(f"Länge des Arrays: {len(calib)}")
        print(f"Erste 5 Werte: {calib[0]:.4f}, {calib[1]:.4f}, {calib[2]:.4f}, {calib[3]:.4f}, {calib[4]:.4f}")
        if calib[0] == 0.0 and calib[50] == 0.0 and calib[100] == 0.0:
            print("!!! ALARM !!! Das Kalibrierungs-Array besteht nur aus Nullen!")
            print("Das bedeutet: Die TXT-Datei ist defekt, falsch formatiert oder das Einlesen schlägt fehl.")
    except Exception as e:
        print(f"Konnte Kalibrierung nicht prüfen: {e}")

    # 2. DER SOLLWERT-BEWEIS
    print("\n--- 2. HARDWARE SOLLWERT-TEST ---")
    print("Sende 50.0 mbar an den Controller...")
    pc.set_pressure_mbar(1, 50.0)
    time.sleep(1.0)
    
    try:
        # Wir greifen tief in die DLL, um zu sehen, was wirklich ankam
        from src.hardware.drivers.elveflow import OB1_Get_Press
        setpoint = c_double(0.0)
        meas = c_double(0.0)
        
        # acq=2 liest den Setpoint (Sollwert), acq=1 den echten Messwert
        OB1_Get_Press(pc._instr_id.value, 1, 2, pc._calib, byref(setpoint), 1000)
        OB1_Get_Press(pc._instr_id.value, 1, 1, pc._calib, byref(meas), 1000)
        
        print(f"Hardware meldet Sollwert (Setpoint): {setpoint.value:.3f} mbar")
        print(f"Hardware meldet Istwert (Measured):  {meas.value:.3f} mbar")
        
    except Exception as e:
        print(f"Fehler beim DLL-Lesezugriff: {e}")
        
    print("\nSchalte Druck ab...")
    pc.set_pressure_mbar(1, 0.0)
    pc.close()
    print("--- TEST COMPLETE ---")

if __name__ == "__main__":
    run_test()