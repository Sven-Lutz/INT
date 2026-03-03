import csv
import time
import random
import os
from datetime import datetime


def generate_mock_csv():
    # Stelle sicher, dass der logs-Ordner existiert
    os.makedirs("logs", exist_ok=True)

    # Dateiname mit Zeitstempel
    filename = f"logs/run_simulated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    # Typische Spalten für eine solche Anlage (passe sie an, falls deine anders heißen)
    headers = ["Timestamp", "Time_s", "P1_mbar", "P2_mbar", "Flow_ml_min", "Volume_ml", "State"]

    with open(filename, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        start_time = time.time()
        vol = 100.0  # Startvolumen in ml

        print("Generiere simulierte Sensordaten...")

        # Simuliere 300 Datenpunkte (bei 5Hz / 0.2s Sample Period = 60 Sekunden Laufzeit)
        for i in range(300):
            t_s = i * 0.2
            ts_str = datetime.fromtimestamp(start_time + t_s).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

            if t_s < 10:
                state = "IDLE"
                p1 = random.uniform(0, 5)
                p2 = random.uniform(0, 5)
                flow = random.uniform(-0.01, 0.01)
            elif t_s < 40:
                state = "FILTRATION"
                p1 = 1200 + random.uniform(-15, 15)  # 1200 mbar Hauptdruck
                p2 = random.uniform(0, 5)
                flow = 1.25 + random.uniform(-0.05, 0.05)  # ~1.25 ml/min
                vol -= (flow / 60) * 0.2  # Volumen nimmt ab
            elif t_s < 50:
                state = "BACKWASH"
                p1 = random.uniform(0, 5)
                p2 = 800 + random.uniform(-10, 10)  # 800 mbar Backwash
                flow = -2.5 + random.uniform(-0.1, 0.1)  # Negativer Flow!
                vol -= (flow / 60) * 0.2
            else:
                state = "VENTING"
                p1 = random.uniform(0, 5)
                p2 = random.uniform(0, 5)
                flow = random.uniform(-0.01, 0.01)

            writer.writerow([ts_str, round(t_s, 2), round(p1, 2), round(p2, 2), round(flow, 3), round(vol, 2), state])

    print(f"✅ ERFOLG: Datei '{filename}' wurde erstellt!")
    print("Du kannst diese nun im 'RUN ANALYSIS' Tab laden.")


if __name__ == "__main__":
    generate_mock_csv()