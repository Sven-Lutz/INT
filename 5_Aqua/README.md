# Process Control

Desktop control and measurement software for a gravity-fed water process.

## Confirmed hardware mapping

- LucidControl COM4
  - logical channel 0 / D01: binary valve
  - logical channel 1 / D02: LED
- LucidControl COM7 / AI4
  - capacitance sensor: channel assignment still to be verified
  - humidity sensor: channel assignment still to be verified
- Bronkhorst ES-FLOW COM8
  - baud rate: 38400
  - node address: 3

## Process path

Water vessel
→ Bronkhorst flow sensor
→ proportional control valve
→ binary valve
→ outlet

## Main goals

1. Drain water at a controlled flow.
2. Measure capacitance and stop at a critical threshold.
3. Record all measurements and process events.
4. Switch the LED on and off.
5. Integrate the validated process into a GUI.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

LucidControl command-line utility must exist at:

```text
C:\Program Files\LucidControl\LucidIoCtrl.exe
```

## Recommended test order

```powershell
python -m tests.test_state_machine
python -m tests.test_safety
python -m tests.test_lucid_do
python -m tests.test_bronkhorst
python -m tests.test_lucid_ai4
python -m tests.test_process
```

## Start command-line process

```powershell
python main.py
```

## Start static GUI prototype

```powershell
python -m gui.app
```

## Important commissioning status

COM4 and COM8 were successfully tested end to end. Water flow was observed with:

- LucidControl COM4
- logical channel 0
- state 1
- Bronkhorst forced-open mode

The AI4 channel assignments and sensor scaling must still be validated before capacitance-based automatic shutdown is enabled.
