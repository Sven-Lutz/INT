# INT

Experimental process-control software for laboratory filtration and Aqua
systems.

## Projects

### Filtration

Process-control and experimental tooling for the filtration setup.

Core areas:

- hardware communication
- pressure and flow control
- experiment workflows
- operator GUI
- telemetry
- data acquisition and logging

Active development branch: `filtration`

Technical documentation: [3_Filtration/README.md](3_Filtration/README.md)

### Aqua

Control software for the Aqua gravity-fed drain system.

Core areas:

- Bronkhorst ES-FLOW integration
- LucidControl analog and digital I/O
- capacitance and humidity acquisition
- valve-position and flow-target control
- target-volume and empty detection
- operator-adjustable controls during runs
- PySide6 operator GUI
- persistent telemetry and chart history
- CSV and event logging
- hardware preflight and fail-safe output handling

Active development branch: `aqua`

Technical and commissioning documentation: [5_Aqua/README.md](5_Aqua/README.md)

## Branch Model

### `main`

Stable integrated repository state.

### `aqua`

Active Aqua development.

### `filtration`

Active Filtration development.

Validated project changes are periodically integrated back into `main`.

## Repository Structure

- `1_Notizen/` — laboratory notes and supporting records
- `2_TransferStage/` — transfer-stage software, configuration, and documentation
- `3_Filtration/` — filtration control software and hardware configuration
- `4_HeadcrabFiltration_Setup_LabView/` — Headcrab Filtration LabVIEW setup area
- `5_Aqua/` — Aqua control application, tests, and commissioning documentation

## Development

- Do not commit generated measurements, runtime logs, or machine-local
  configuration.
- Keep local virtual environments outside version control.
- Hardware-facing changes require physical commissioning before they are
  considered validated.
- Project-specific setup and operating instructions live in the README inside
  each project directory.

## Status

Filtration and Aqua are active laboratory process-control projects.
