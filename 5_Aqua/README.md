# Aqua Process Control

Desktop control, live telemetry, diagnostics, and measurement logging for the gravity-fed Aqua water process.

## Process model

The operator independently selects how to drain and when to stop. One control
method is active per run:

- direct Bronkhorst Valve Position [%], or
- closed-loop Bronkhorst Flow Target [ml/min].

Empty detection and target drained volume are independent stop conditions;
either can be enabled together, and the first reached condition wins:

```text
DISCONNECTED
  -> Connect
READY
  -> Start draining
RUNNING                selected Valve Position or Flow Target active
  -> sample flow, capacitance, humidity, temperature and device state
  -> integrate current Run Volume and cumulative Session Total
  -> capacitance <= empty threshold for N consecutive samples, or
  -> Run Volume >= enabled Target Volume
STOPPING
  -> proportional valve closed
  -> downstream binary valve closed
STOPPED
  -> next run can be started without reconnecting
```

A manual stop is possible at any time. During RUNNING the selected control
mode remains fixed, while its active target and the LED can be changed with
verified hardware commands. Stop-condition settings remain locked for that
run.

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

### Lucid Digital commissioning requirements

READY requires the following persistent hardware configuration and readable
logical state:

| Port / channel | Function | `outDiMode` | `outDiInverted` | Safe logical state |
| --- | --- | --- | --- | --- |
| COM4 CH0 | Binary Valve | `reflect` | `off` | `0` / closed |
| COM4 CH1 | LED | `reflect` | `off` | `0` / off |

Normal Aqua Connect only inspects this configuration. It does **not** run
`-soutDiMode=reflect -p` or otherwise rewrite persistent Lucid settings. A
reported mode such as `inactive` prevents READY and must be corrected during
explicit hardware commissioning.

On the commissioned Windows installation, successful `LucidIoCtrl` commands
commonly return exit code `1`; exit codes `0` and `1` are therefore accepted
only when stdout and stderr contain no Lucid error. `(0x10) Internal I/O read
error` and `(0x11) Invalid number of bytes received` are transient protocol
errors. Aqua retries read-only commands at most three times, but never blindly
repeats an actuator write.

The authoritative output state is the logical read-back from `-tL -r`.
`outDiValue` is internal/configured diagnostic information only and may
disagree with the actual output. It is never used for valve/LED state,
safe-state verification, or READY.

`CAPACITANCE_CHANNEL` and `HUMIDITY_CHANNEL` in `config.py` are the single source of truth for the complete AI signal chain:

```text
AI4 channel -> acquisition -> SystemMeasurement -> CSV -> telemetry -> chart
```

Run `python -m tests.test_channel_map` during commissioning to verify the assignment: draining the vessel must move the capacitance value, not the humidity value.

## Sensor semantics

### Capacitance

The acquisition keeps the raw AI4 voltage and a separately scaled capacitance
process value. The configured values are currently approximate commissioning
references, not confirmed physical voltages:

```text
FILLED  ~ 25 scaled units
   |  draining
   v
EMPTY   ~  0 scaled units
```

The GUI reports the scaled value, raw AI4 voltage, and semantic state
(`FILLED`, `DRAINING`, `EMPTY`, `UNKNOWN`). The capacitance-based stop uses
one direction:

```text
capacitance <= empty threshold
```

The condition is debounced. `CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES` consecutive readings must remain at or below the threshold before the run stops.

### Humidity

Humidity is converted from AI4 voltage to `% RH` in `devices/sensors.py` and plotted on a fixed 0–100 % axis. Rising humidity is the remaining upper safety limit. `CRITICAL_HUMIDITY_PERCENT` stays disabled until the sensor has been calibrated.

## Operator GUI

Start the integrated GUI with:

```powershell
python -m gui.app
```

The GUI builds the real `WaterProcessController`; it is no longer a static widget prototype.

### Live Telemetry

While connected, the hardware worker polls telemetry even when no drain run is active. During a run, the same samples used for safety checks and CSV logging feed the GUI. The header reports telemetry freshness (`LIVE` / `STALE`).

Visible telemetry includes:

- flow
- capacitance value and fill state
- humidity
- commanded valve opening and Bronkhorst valve output
- cumulative Session Total with current Run Volume shown separately
- Bronkhorst temperature
- Bronkhorst alarm register
- downstream binary valve and LED state

### Interactive Live Charts

The bounded chart layer retains history across all runs in the current Aqua
session. Chart time is monotonic session time, so a new run never restarts the
X coordinate at zero. The drained-volume plot uses cumulative Session Total;
run-specific volume remains available in telemetry and `ProcessSummary`.

| Metric | Unit | Y axis |
| --- | --- | --- |
| Flow | ml/min | dynamic from zero |
| Capacitance | scaled | fixed 0 to 30 with current defaults |
| Humidity | % | fixed 0 to 100 % |
| Valve position | % | fixed 0 to 100 % |
| Drained volume | ml | dynamic from zero |
| Temperature | °C | fixed 0 to 50 °C |

Interaction:

- click a chart to focus it
- click a telemetry card to focus the corresponding chart
- hover the line for exact time/value information
- use metric toggle buttons to configure the overview
- select `10 s`, `30 s`, `60 s`, `2 min`, `5 min`, `10 min`, or
  `Full session`; changing the window never deletes retained samples
- press `Esc` or `Overview` to return from a focused chart

### Operator Log

The `Operator Log` tab receives standard Python `logging` records from the Aqua runtime. It supports severity filtering, auto-scroll, and a bounded in-memory view. The same runtime information is persisted independently of the GUI to:

```text
measurements/aqua_runtime.log
```

The runtime log rotates automatically. Generated logs and measurements remain ignored by Git.

### Developer Insights

The `Developer Insights` tab exposes the diagnostic state that is intentionally hidden from the normal operator controls, including:

- process state
- raw AI4 voltages
- Bronkhorst control mode
- raw valve output and converted valve output percentage
- flow setpoint readback
- binary valve / LED state
- Lucid Digital preflight, critical configuration/read-back, cached state,
  optional `outDiValue`, and last communication error
- empty-detector status
- in-memory measurement/event counts
- active and most recent measurement/event CSV paths
- summary CSV path
- active run control/stop configuration, Run Volume, Session Total, and
  pending live-command count

This view is meant for commissioning and fault diagnosis, not process control.

## Logging and measurement data

Each drain run produces:

- `process_control_measurements_<timestamp>.csv`
- `process_control_events_<timestamp>.csv`
- one row in `process_control_summaries.csv`

The CSV logger and runtime logger serve different purposes: CSV files are structured process data; `aqua_runtime.log` records application, hardware, and GUI/runtime events.

## Process path

```text
Water vessel
  -> Bronkhorst flow sensor / proportional valve
  -> downstream binary valve
  -> outlet
```

## Main goals

1. Drain using either direct Valve Position or closed-loop Flow Target.
2. Stop on empty detection, Target Volume, manual STOP, or safety conditions.
3. Provide live operator telemetry and interactive run charts.
4. Record structured measurements, process events, summaries, and runtime diagnostics.
5. Expose raw Developer Insights for commissioning without cluttering the operator workflow.
6. Adjust the active target and verified LED output during a run.

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

## Operator startup

For normal operation, double-click the workstation shortcut:

```text
Aqua Process Control
```

No command line, virtual-environment activation, Git knowledge, or repository
navigation is required. The shortcut starts `start_aqua.ps1`, which locates a
pre-installed `.venv` in `5_Aqua` or its parent directory and runs the safe
GUI entry point with `pythonw.exe`. No terminal window remains visible.

The desktop shortcut contains the absolute path of the current workstation;
`start_aqua.ps1` itself resolves all project paths relative to its own
location. The Python environment and hardware dependencies must already be
installed and commissioned. Startup diagnostics are retained under
`5_Aqua/logs/`, while application diagnostics continue to use the bounded
runtime log documented above.

A maintainer can create or update the current user's shortcut at any time:

```powershell
cd 5_Aqua
powershell -ExecutionPolicy Bypass -File .\install_desktop_shortcut.ps1
```

## Recommended test order

```powershell
python -m tests.test_state_machine
python -m tests.test_safety
python -m tests.test_empty_detection
python -m tests.test_controller_reuse
python -m pytest -q tests/test_process_sessions.py
python -m tests.test_lucid_do
python -m tests.test_bronkhorst
python -m tests.test_lucid_ai4
python -m tests.test_channel_map
python -m tests.test_process
```

The state-machine, safety, empty-detection, and controller-reuse tests run without Aqua hardware. Device/channel/process tests require the corresponding hardware.

## Command-line process

The validated backend can still be run without the GUI:

```powershell
python main.py
```

## Commissioning status

COM4 and COM8 were successfully tested end to end. Water flow was observed with:

- LucidControl COM4
- logical channel 0
- state 1
- Bronkhorst forced-open mode

Still to confirm on the physical Aqua setup:

- `CAPACITANCE_EMPTY_THRESHOLD` (currently 5 scaled units) and
  `CAPACITANCE_FILLED_VALUE` are initial estimates. The configured full value
  near 25 must not be interpreted as a physically confirmed 25 V signal.
- `CAPACITANCE_VALUE_PER_VOLT` / `CAPACITANCE_VALUE_OFFSET` currently pass the
  raw reading through unchanged; verify the actual sensor transfer function
  and AI4 electrical range during commissioning.
- `HUMIDITY_VOLTAGE_AT_0_PERCENT` / `HUMIDITY_VOLTAGE_AT_100_PERCENT` assume a linear 0–10 V sensor.
- `CRITICAL_HUMIDITY_PERCENT` remains disabled until humidity calibration is complete.
