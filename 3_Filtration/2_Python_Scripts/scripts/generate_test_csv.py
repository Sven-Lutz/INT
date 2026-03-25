import csv
import random
import math

# Konfiguration
filename = "test_run_telemetry.csv"
sample_rate_s = 0.2
total_duration_s = 600  # 10 Minuten Experiment

# Startwerte
t_s = 0.0
p1_meas = 0.0
volume_ml = 0.0

def add_noise(value, noise_level):
    """Fügt ein leichtes Sensor-Rauschen hinzu."""
    return max(0.0, value + random.uniform(-noise_level, noise_level))

with open(filename, mode="w", newline="", encoding="utf-8") as f:
    # Die exakten Spaltennamen aus deinem RunTelemetryStore
    fieldnames = [
        "schema_version", "run_id", "ts", "t_s", "step", "event", 
        "flow", "p1_set", "p1_meas", "p2_set", "p2_meas", 
        "volume_ml", "loss_ml", "valves", "manual_active", 
        "pressure_json", "extra_json"
    ]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    
    # Optionale Preamble (wie im echten Experimentator)
    f.write("# created=2026-03-25T14:00:00\n")
    f.write("# host=LAB-PC-01\n")
    f.write("# cfg={'simulation': True}\n")
    writer.writeheader()

    while t_s <= total_duration_s:
        # Phase 0: Befüllung (0 - 60s)
        if t_s < 60:
            step = "PHASE_0_AUTO_FILL"
            p1_set = 200.0
            p1_meas = add_noise(200.0 * (1 - math.exp(-t_s/5)), 5.0)
            volume_ml += add_noise(50.0 * sample_rate_s, 2.0) # Schnelle Befüllung

        # Phase A: Ramp Up (60 - 180s)
        elif t_s < 180:
            step = "PHASE_A_RAMP"
            progress = (t_s - 60) / 120.0
            p1_set = 200.0 + (1800.0 * progress) # Rampe auf 2000mbar
            p1_meas = add_noise(p1_set, 10.0)
            volume_ml += add_noise(25.0 * sample_rate_s, 1.0)

        # Phase B: Steady State (180 - 480s)
        elif t_s < 480:
            step = "PHASE_B_STEADY"
            p1_set = 2000.0
            p1_meas = add_noise(2000.0, 15.0)
            # Bei hohem Druck fließt es konstant
            volume_ml += add_noise(10.0 * sample_rate_s, 0.5) 

        # Phase C: Ramp Down (480 - 600s)
        else:
            step = "PHASE_C_RAMP_DOWN"
            progress = (t_s - 480) / 120.0
            p1_set = max(0.0, 2000.0 - (2000.0 * progress))
            p1_meas = add_noise(p1_set, 8.0)
            # Fluss nimmt mit fallendem Druck ab
            volume_ml += add_noise(2.0 * sample_rate_s, 0.1)

        # Zeile schreiben
        writer.writerow({
            "schema_version": "1",
            "run_id": "test_run_001",
            "ts": "2026-03-25T14:00:00",
            "t_s": f"{t_s:.3f}",
            "step": step,
            "event": "",
            "flow": f"{random.uniform(0.1, 50.0):.2f}",
            "p1_set": f"{p1_set:.2f}",
            "p1_meas": f"{p1_meas:.2f}",
            "p2_set": "0.00",
            "p2_meas": "0.00",
            "volume_ml": f"{volume_ml:.2f}",
            "loss_ml": "0.00",
            "valves": "filtration",
            "manual_active": "0",
            "pressure_json": "",
            "extra_json": ""
        })
        
        t_s += sample_rate_s

print(f"Erfolgreich generiert: {filename} ({int(total_duration_s/sample_rate_s)} Datenpunkte)")