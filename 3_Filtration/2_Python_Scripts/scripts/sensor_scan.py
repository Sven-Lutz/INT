# sensor_scan.py
import propar

def scan_bronkhorst_sensor(port: str = "COM5"):
    # Typische Bronkhorst Baudraten und Node-Adressen
    baudrates = [38400, 9600, 4800, 19200, 115200, 57600, 115200, 230400, 460800]
    nodes = [1, 3, 128] 
    
    print(f"Starte Sensor-Scan auf {port}...")
    
    for baud in baudrates:
        for node in nodes:
            print(f"  -> Teste Baudrate: {baud}, Node: {node}")
            try:
                # Verbindung initialisieren
                instrument = propar.instrument(port, baudrate=baud, address=node)
                # Parameter 113 (User Tag) abfragen
                user_tag = instrument.readParameter(113)
                
                if user_tag is not None:
                    print(f"\n✅ BINGO! Sensor gefunden!")
                    print(f"   Baudrate: {baud}")
                    print(f"   Node-Adresse: {node}")
                    print(f"   Sensor-Name: '{user_tag}'")
                    return # Erfolgreich, wir können abbrechen
            except Exception as e:
                # Bei Fehlern ignorieren und nächste Kombination testen
                pass
                
    print("\n❌ Scan beendet. Kein Sensor geantwortet. Kabel und COM-Port prüfen!")

if __name__ == "__main__":
    scan_bronkhorst_sensor()