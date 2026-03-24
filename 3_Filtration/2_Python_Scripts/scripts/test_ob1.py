import time
from src.hardware.drivers.pressure_controller import PressureController

def run_test():
    print("--- STARTING ACTIVE ELVEFLOW TEST ---")
    
    cfg_dict = {
        "backend": "elveflow",
        "device_name": "COM10",
        "regulator_types": [5, 5, 0, 0],
        "calib_path": "U:\\PelliKAn\\3_Filtration\\4_Config\\OB1_Calib_latest.txt",
        "autoload_calib": True,
        "pressure_limit": 2000.0
    }
    
    pc = PressureController(cfg_dict)
    print("Connecting to OB1...")
    pc.connect()
    
    # Wir feuern 50 mbar auf Kanal 1! (ohne ramp=False)
    print("\n>>> SENDE 50.0 mbar AUF KANAL 1 <<<")
    try:
        pc.set_pressure_mbar(1, 50.0)
    except Exception as e:
        print(f"Fehler beim Druckaufbau: {e}")

    # Wir lesen, was passiert...
    print("Lese Sensoren für 5 Sekunden...")
    for i in range(10):
        p1 = pc.get_pressure_mbar(1)
        p2 = pc.get_pressure_mbar(2)
        print(f"Tick {i+1}/10 | CH1: {p1:.3f} mbar | CH2: {p2:.3f} mbar")
        time.sleep(0.5)
        
    print("\n>>> SCHALTE DRUCK AB (0.0 mbar) <<<")
    pc.set_pressure_mbar(1, 0.0)
    
    print("Closing connection...")
    pc.close()
    print("--- TEST COMPLETE ---")

if __name__ == "__main__":
    run_test()