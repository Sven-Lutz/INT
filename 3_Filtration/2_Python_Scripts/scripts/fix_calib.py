import os

def fix_file():
    path = r"U:\PelliKAn\3_Filtration\4_Config\OB1_Calib_latest.txt"
    
    print(f"Lese Datei: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        print("\n--- ORIGINAL (Erste 5 Zeilen) ---")
        for i in range(min(5, len(lines))):
            print(repr(lines[i].strip()))
            
        # Brutale Reparatur: Alle Kommas zu Punkten machen
        fixed_lines = [line.replace(",", ".") for line in lines]
        
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(fixed_lines)
            
        print("\n--- REPARIERT (Erste 5 Zeilen) ---")
        for i in range(min(5, len(fixed_lines))):
            print(repr(fixed_lines[i].strip()))
            
        print("\nDatei erfolgreich repariert! Kommas sind jetzt Punkte.")
        
    except Exception as e:
        print(f"Fehler beim Zugriff: {e}")

if __name__ == "__main__":
    fix_file()