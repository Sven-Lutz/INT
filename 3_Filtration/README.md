# Filtration

Laboratory process-control software and configuration for the filtration
setup.

## Components

- `2_Python_Scripts/` contains the Pellikan OS operator application, hardware
  drivers, experiment workflow, telemetry, logging, and tests.
- `4_Config/` contains filtration hardware configuration and calibration
  support files.

See [2_Python_Scripts/README.md](2_Python_Scripts/README.md) for installation,
operation, architecture, simulation, testing, and hardware details.

Active development takes place on the `filtration` branch. Hardware-facing
changes must be verified on the laboratory setup; tests marked `hardware` are
not part of the hardware-independent test suite.
