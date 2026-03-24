import time
import ctypes
from ctypes import byref, c_double, c_long
from src.hardware.drivers.elveflow import get_elveflow, OB1_Initialization, OB1_Get_Press, OB1_Set_Press

def run_test():
    print("--- FINAL HARDWARE VERIFICATION TEST ---")
    dll_wrapper = get_elveflow()
    if dll_wrapper is None:
        print("DLL nicht gefunden!")
        return

    # 1. MANUELLE KALIBRIERUNG (Linearer Standard 0-2000 mbar)
    calib = (c_double * 1000)()
    for i in range(1000):
        calib[i] = float(i) * 2.0 - 1000.0
    
    print(f"Kalibrierung vorbereitet.")

    # 2. INITIALISIERUNG (Jetzt mit c_long für die ID!)
    instr_id = c_long(0) 
    print("Verbinde mit OB1 auf COM10...")
    
    # argument 6 ist jetzt korrekt ein Pointer auf ein Long (LP_c_long)
    err = OB1_Initialization(b"COM10", 5, 5, 0, 0, byref(instr_id))
    
    if err != 0:
        print(f"Initialisierung fehlgeschlagen! Code: {err}")
        return
    
    # Wir speichern die ID als einfache Python-Zahl für die weiteren Aufrufe
    id_val = int(instr_id.value)
    print(f"OB1 BEREIT. Vergebene ID: {id_val}")

    # 3. AKTIVER DRUCK-TEST
    target = 50.0 
    print(f"\n>>> SENDE {target} mbar AUF KANAL 1 <<<")
    
    # Set_Press Aufruf
    OB1_Set_Press(id_val, 1, target, byref(calib), 1000)
    
    print("Warte 2 Sekunden...")
    time.sleep(2.0)
    
    print("Lese Sensoren...")
    for i in range(10):
        meas = c_double(0.0)
        # Get_Press Aufruf
        OB1_Get_Press(id_val, 1, 1, byref(calib), byref(meas), 1000)
        print(f"MESSUNG {i+1}/10: {meas.value:.3f} mbar")
        time.sleep(0.5)

    print("\n>>> SCHALTE DRUCK AB <<<")
    OB1_Set_Press(id_val, 1, 0.0, byref(calib), 1000)
    
    # Sauberer Abschluss
    if hasattr(dll_wrapper, 'OB1_Destructor'):
        dll_wrapper.OB1_Destructor(id_val)
    
    print("--- TEST ERFOLGREICH BEENDET ---")

if __name__ == "__main__":
    run_test()