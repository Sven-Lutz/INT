# Pellikan OS — Filtration Experiment Control

Desktop GUI for controlling tangential-flow filtration (TFF) experiments: backwash,
manual filling, pressure ramp (Phase A), steady-state filtration (Phase B), and ramp-down
(Phase C). Live telemetry, valve control, progress tracking, and a LAN-accessible web monitor.

---

## Quick Start

```bash
# 1. Create environment (Python 3.11 recommended)
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch
python -m src.gui.app
```

The app auto-discovers hardware on startup. If no hardware is present it runs in
**simulation mode** (all sensor readings are zero; valve/pressure commands are no-ops).

---

## Experiment Flow

```
[Backwash] → [Manual Filling *] → [Phase A: Ramp Up] → [Phase B1: Steady State]
          → [Phase B2: Drying (optional)] → [Phase C: Ramp Down]
```

`*` Filling is the only manual step — the operator enters the fill volume and confirms.
All other phase transitions happen automatically.

---

## Directory Layout

```
src/
  backend/core/        — hardware abstraction (DeviceManager, Experimentator)
  hardware/drivers/    — low-level sensor/valve/pressure drivers
  config/              — YAML configs (runtime/ overrides defaults/)
  gui/
    frames/            — UI panels (left, right, top, analysis)
    data/              — ExperimentWorker, logger
    monitor/           — LAN web dashboard (MonitorServer)
    style/             — Qt theme
  utils/               — path helpers, config manager
tests/                 — pytest test suite
logs/                  — app.log (rotating) + runs/<timestamp>.log per run
```

---

## Web Monitor

When a run starts, the desktop status bar shows a URL like:

```
http://192.168.1.x:8765/?token=<secret>
```

Open this on any phone or tablet on the same network for a live dashboard (pressure, flow,
volume, phase timeline, Chart.js history chart).

The token is stripped from the URL after first load and stored in `sessionStorage` so it
does not appear in browser history.

---

## Development

```bash
# Install pre-commit hooks (runs black, isort, flake8, ast-check on every commit)
pip install pre-commit
pre-commit install

# Run tests
pytest

# Lint manually
flake8 src/ --max-line-length=100 --extend-ignore=E203,W503
black --check --line-length=100 src/
```

### Code style

- **Black** + **isort** (profile=black), line length 100.
- **Type hints** on all public functions.
- No bare `except: pass` — always log the exception.
- Hardware calls are isolated in `DeviceManager`; never import driver modules outside `src/backend/`.

### Configuration

Runtime overrides live in `src/config/runtime/*.yaml`. The `defaults/` folder contains the
shipped defaults — do not edit those; edit `runtime/` instead. Config is loaded once at
startup via `ConfigManager` (singleton).

---

## Hardware Requirements

| Component | Interface | Driver |
|-----------|-----------|--------|
| OB1 pressure controller | USB / serial | `propar` |
| Flow sensor | USB / RS-232 | custom |
| Valve relay board | USB-serial | custom |

Run in simulation mode (`ui.sim_mode: true` in `general.yaml`) if hardware is unavailable.

---

## Logs

- `logs/app.log` — rotating, 5 × 10 MB backups; survives across restarts
- `logs/runs/YYYYMMDD_HHMMSS.log` — per-run log, created when a sequence starts
- Telemetry CSV — written to the run output directory configured in `general.yaml`
