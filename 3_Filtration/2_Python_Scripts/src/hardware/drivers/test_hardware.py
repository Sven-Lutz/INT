import ctypes
# Passe den Import-Pfad an, falls deine Ordnerstruktur leicht abweicht
from src.hardware.drivers.elveflow import (
    get_elveflow,
    OB1_Initialization,
    OB1_Destructor
)


def test_connection():
    print("--- Elveflow OB1 Verbindungs-Test ---")

    # 1. DLL Laden testen
    try:
        dll = get_elveflow()
        print(f"[OK] DLL erfolgreich geladen von: {dll.dll_path}")
    except Exception as e:
        print(f"[FEHLER] DLL konnte nicht geladen werden: {e}")
        return

    # 2. Verbindung testen
    print("\nVersuche OB1 zu initialisieren...")

    # ctypes Variable für die Instrumenten-ID vorbereiten
    instr_id = ctypes.c_int32(-1)

    # WICHTIG: Hier den tatsächlichen COM-Port eintragen!
    com_port = "COM10"

    # OB1_Initialization aufrufen (com_port, reg1, reg2, reg3, reg4, instr_id_ptr)
    # Die Regler-Typen (hier 0,0,0,0) müssen ggf. an dein spezifisches Gerät angepasst werden.
    error_code = OB1_Initialization(com_port, 0, 0, 0, 0, ctypes.byref(instr_id))

    print(f"-> Zurückgegebener Fehlercode: {error_code}")
    print(f"-> Zugewiesene Instrument ID: {instr_id.value}")

    # 3. Auswertung
    if error_code == 0 and instr_id.value >= 0:
        print("\n[ERFOLG] Das Gerät kommuniziert einwandfrei mit deinem neuen Code!")

        # Gerät wieder sauber freigeben
        OB1_Destructor(instr_id.value)
        print("OB1 sicher getrennt.")
    else:
        print("\n[FEHLGESCHLAGEN] Keine Verbindung möglich.")
        print("Mögliche Ursachen:")
        print("  - Falscher COM-Port (bitte im Windows Geräte-Manager unter 'Anschlüsse (COM & LPT)' prüfen).")
        print(
            "  - Das Gerät wird gerade noch von einer anderen Software (z.B. NI MAX oder Elveflow Smart Interface) blockiert.")
        print("  - USB-Kabel oder Stromversorgung nicht richtig eingesteckt.")


if __name__ == "__main__":
    test_connection()