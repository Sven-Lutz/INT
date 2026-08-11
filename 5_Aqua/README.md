# Process Control

Desktop control and measurement software for a gravity-fed water process.

## Process model

The proportional valve is the manipulated variable, not a flow setpoint.
The vessel is drained from above and the run ends when the capacitance
sensor no longer sees water:

```text
IDLE
  -> Start
DRAINING              valve at the configured opening (100 % by default)
  -> capacitance measured every sample
  -> capacitance <= empty threshold for N consecutive samples
STOPPING
  -> valve closed
COMPLETED
```

A manual stop is possible at any time. Closed-loop flow control
(flow setpoint -> controller -> valve position) still exists in the
backend for diagnostics but is not part of the operator workflow —
pass `flow_setpoint_ml_min` to `WaterProcessController.start()` to use
it.

## Confirmed hardware mapping

- LucidControl COM4
  - logical channel 0 / D01: binary valve
  - logical channel 1 / D02: LED
- LucidControl COM7 / AI4
  - channel 0: capacitance sensor
  - channel 1: humidity sensor
- Bronkhorst ES-FLOW COM8
  - baud rate: 38400
  - node address: 3

`CAPACITANCE_CHANNEL` and `HUMIDITY_CHANNEL` in `config.py` are the only
place where these AI4 channels are defined. Everything downstream —
device read, `SystemMeasurement`, CSV, GUI value, chart axis — follows
those two constants, so a swapped sensor is corrected in exactly one
place. Run `python -m tests.test_channel_map` to verify the assignment:
draining the vessel must move the capacitance value, not the humidity
value.

## Sensor semantics

The capacitance sensor is read as a voltage — volts are its unit
throughout — but it behaves almost binary:

```text
FILLED  ~ 25 V
   |  draining
   v
EMPTY   ~  0 V
```

Accordingly the GUI reports a value in volts plus a state (`FILLED`,
`DRAINING`, `EMPTY`, `UNKNOWN`) and there is only one stop condition:

```text
capacitance <= empty threshold
```

There is no "at or above" direction to pick. The stop is debounced —
`CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES` readings in a row must stay at
or below the threshold before the process stops, so a single noisy
sample cannot abort a run.

Humidity is converted from voltage to `% RH` in the acquisition layer
(`devices/sensors.py`) and is displayed and plotted as a percentage on a
fixed 0–100 % axis. Rising humidity indicates a leak and is therefore
the one remaining upper safety limit
(`CRITICAL_HUMIDITY_PERCENT`, disabled until calibrated).

## GUI

The window is wired to the real controller. `Connect` opens the
Bronkhorst, the LucidControl DO and the AI4 on a background thread —
every device call blocks on a serial port and must not run in the GUI
thread — and reports each step. A failed connect produces an error entry
in the log, a dialog naming the port, and an entry under
`Developer Insights → Last error`, instead of silently doing nothing.
`Connect` stays available so the attempt can be repeated.

Buttons follow the process state: `Start draining` needs a connection,
`Stop` is only active during a run, LED and the run parameters lock while
draining.

**Logging** shows one line per event with a level (`INFO`, `SUCCESS`,
`WARNING`, `ERROR`, `DEBUG`). Tracebacks go to `DEBUG` and stay hidden
until `Show debug output` is ticked.

**Developer Insights** shows the values behind the telemetry: configured
ports and AI4 channel assignment, Bronkhorst control mode and raw alarm
word, raw valve output, both raw channel voltages next to their converted
values, sample count, configured versus measured sample interval,
integrated volume and the last run summary.

**Charts** are interactive:

- `Time window` switches all four plots between 10 s and the full run.
- Clicking a point reads off its exact time and value below the plot.
- Dragging zooms into a region, which also pauses the live follow.
- Double-clicking resets the zoom and resumes following.

Colour is used only where it carries information: process state,
capacitance state, alarm, LED state and log level. Everything else keeps
the native Qt look.

## Chart axes

`gui/charting.py` holds a central `METRIC_CONFIG`. Each physical
quantity has its own unit and range instead of one generic autoscaling
rule:

| Metric         | Unit   | Y axis                     |
| -------------- | ------ | -------------------------- |
| Flow           | ml/min | 0 to 1.15 x observed max   |
| Capacitance    | V      | 0 to 30 (fixed)            |
| Humidity       | %      | 0 to 100 (fixed)           |
| Valve position | %      | 0 to 100 (fixed)           |
| Drained volume | ml     | 0 to 1.15 x observed max   |
| Temperature    | °C     | 0 to 50 (fixed)            |

The telemetry cards format their values through the same definitions, so
a number and its plot can never disagree about the unit.

## Process path

Water vessel
→ Bronkhorst flow sensor
→ proportional control valve
→ binary valve
→ outlet

## Main goals

1. Drain water at a configured valve opening.
2. Measure capacitance and stop automatically once the vessel is empty.
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
python -m tests.test_empty_detection
python -m tests.test_lucid_do
python -m tests.test_bronkhorst
python -m tests.test_lucid_ai4
python -m tests.test_channel_map
python -m tests.test_process
```

`test_state_machine`, `test_safety` and `test_empty_detection` run
without hardware.

## Start command-line process

```powershell
python main.py
```

## Start static GUI prototype

```powershell
python -m gui.app
```

## Important commissioning status

COM4 and COM8 were successfully tested end to end. Water flow was
observed with:

- LucidControl COM4
- logical channel 0
- state 1
- Bronkhorst forced-open mode

Still open:

- `CAPACITANCE_EMPTY_THRESHOLD` (2.0 V) and `CAPACITANCE_FILLED_VALUE`
  (12.5 V) are first estimates from the observed 25 V / 0 V behaviour.
  Confirm them against a real drain run.
- `CAPACITANCE_VALUE_PER_VOLT` / `CAPACITANCE_VALUE_OFFSET` pass the
  reading through unchanged, which is correct as long as the sensor is
  wired straight to the AI4 input.
- `HUMIDITY_VOLTAGE_AT_0_PERCENT` / `HUMIDITY_VOLTAGE_AT_100_PERCENT`
  assume a 0–10 V sensor. Confirm against the sensor data sheet.
- `CRITICAL_HUMIDITY_PERCENT` stays disabled until the humidity sensor
  has been calibrated.
