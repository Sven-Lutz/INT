import time
from src.hardware.drivers.pressure_controller import PressureController

def run_test():
    print("--- STARTING ELVEFLOW PRESSURE TEST ---")
    
    # 1. Wir übergeben die Parameter exakt so, wie sie in der reparierten YAML stehen
    cfg_dict = {
        "backend": "elveflow",
        "device_name": "COM10",
        "regulator_types": [5, 5, 0, 0],
        "calib_path": "U:\\PelliKAn\\3_Filtration\\4_Config\\OB1_Calib_latest.txt",
        "autoload_calib": True,
        "pressure_limit": 2000.0
    }
    
    print(f"Target Calib Path: {cfg_dict['calib_path']}")
    print(f"Target Regulators: {cfg_dict['regulator_types']}")
    
    # 2. Controller hochfahren
    pc = PressureController(cfg_dict)
    print("Connecting to OB1...")
    pc.connect()
    
    # 3. Wir fragen die Sensoren 10 Mal im Halbsekundentakt ab
    print("Reading pressures...")
    for i in range(10):
        p1 = pc.get_pressure_mbar(1)
        p2 = pc.get_pressure_mbar(2)
        print(f"Tick {i+1}/10 | CH1: {p1:.3f} mbar | CH2: {p2:.3f} mbar")
        time.sleep(0.5)
        
    print("Closing connection...")
    pc.close()
    print("--- TEST COMPLETE ---")

if __name__ == "__main__":
    run_test()