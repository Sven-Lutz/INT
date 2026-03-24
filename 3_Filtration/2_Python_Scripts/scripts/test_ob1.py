import time
from ctypes import byref, c_double
from src.hardware.drivers.elveflow import get_elveflow, OB1_Initialization, OB1_Get_Press, OB1_Set_Press

def run_test():
    print("--- MANUAL CALIBRATION HARDWARE TEST (FIXED TYPES) ---")
    dll_wrapper = get_elveflow()
    if dll_wrapper is None:
        print("DLL nicht gefunden!")
        return

    # 1. MANUELLE KALIBRIERUNG BAUEN
    # Das Array selbst MUSS ctypes bleiben, damit die DLL es versteht
    calib = (c_double * 1000)()
    for i in range(1000):
        calib[i] = float(i) * 2.0 - 1000.0
    
    print(f"Manuelle Kalibrierung erstellt. Check: {calib[0]:.1f} ... {calib[500]:.1f}")

    # 2. INITIALISIERUNG
    instr_id = c_double(0.0)
    print("\nVerbinde mit OB1 auf COM10...")
    # Hier geben wir die Python-Zahlen 5, 5, 0, 0 direkt an
    err = OB1_Initialization(b"COM10", 5, 5, 0, 0, byref(instr_id))
    
    if err != 0:
        print(f"Initialisierung fehlgeschlagen! Code: {err}")
        return
    print(f"OB1 Bereit. ID: {instr_id.value}")

    # 3. AKTIVER DRUCK-TEST
    target = 50.0  # Einfach ein Python float
    print(f"\n>>> Sende {target} mbar auf Kanal 1 <<<")
    
    # OB1_Set_Press erwartet laut Pylance: (int, int, float, pointer, int)
    OB1_Set_Press(int(instr_id.value), 1, target, byref(calib), 1000)
    
    print("Warte 2s auf Druckaufbau...")
    time.sleep(2.0)
    
    print("Lese Sensoren...")
    for i in range(10):
        meas = c_double(0.0)
        # OB1_Get_Press braucht für meas einen Pointer
        OB1_Get_Press(int(instr_id.value), 1, 1, byref(calib), byref(meas), 1000)
        print(f"[{i+1}/10] Kanal 1: {meas.value:.3f} mbar")
        time.sleep(0.5)

    print("\n>>> Schalte Druck ab <<<")
    OB1_Set_Press(int(instr_id.value), 1, 0.0, byref(calib), 1000)
    
    # Destructor (Sauber trennen)
    if hasattr(dll_wrapper, 'OB1_Destructor'):
        dll_wrapper.OB1_Destructor(instr_id.value)
    
    print("--- TEST BEENDET ---")

if __name__ == "__main__":
    run_test()