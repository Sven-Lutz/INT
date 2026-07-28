from pathlib import Path


# =============================================================================
# PROJECT PATHS
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent

LUCID_IO_CTRL_EXE = Path(
    r"C:\Program Files\LucidControl\LucidIoCtrl.exe"
)

MEASUREMENT_DIRECTORY = BASE_DIR / "measurements"


# =============================================================================
# BRONKHORST ES-FLOW
# =============================================================================

BRONKHORST_PORT = "COM8"
BRONKHORST_BAUDRATE = 38_400
BRONKHORST_NODE_ADDRESS = 3


# =============================================================================
# LUCIDCONTROL DIGITAL OUTPUTS — COM4
# =============================================================================

LUCID_DO_PORT = "COM4"

# Logical channel 0 corresponds to physical output D01.
BINARY_VALVE_CHANNEL = 0

# Logical channel 1 corresponds to physical output D02.
LED_CHANNEL = 1

BINARY_VALVE_OPEN_STATE = 1
BINARY_VALVE_CLOSED_STATE = 0

LED_ON_STATE = 1
LED_OFF_STATE = 0


# =============================================================================
# LUCIDCONTROL ANALOG INPUTS — COM7 / AI4
# =============================================================================

LUCID_AI_PORT = "COM7"

# Must still be confirmed experimentally.
CAPACITANCE_CHANNEL = 0
HUMIDITY_CHANNEL = 1


# =============================================================================
# PROCESS SETTINGS
# =============================================================================

DEFAULT_FLOW_SETPOINT_ML_MIN = 100.0
SAMPLE_INTERVAL_SECONDS = 0.5
MAXIMUM_ALLOWED_FLOW_ML_MIN = 200.0


# =============================================================================
# SAFETY LIMITS
# =============================================================================

# Keep disabled until the capacitance sensor has been calibrated.
CRITICAL_CAPACITANCE_VALUE: float | None = None

# Keep disabled until the humidity sensor has been calibrated.
CRITICAL_HUMIDITY_PERCENT: float | None = None


# =============================================================================
# DATA LOGGING
# =============================================================================

CSV_DELIMITER = ";"
MEASUREMENT_FILE_PREFIX = "process_control"
DATETIME_FORMAT = "%Y-%m-%d_%H-%M-%S"


# =============================================================================
# CONFIGURATION VALIDATION
# =============================================================================

def validate_configuration() -> None:
    if not LUCID_IO_CTRL_EXE.is_file():
        raise FileNotFoundError(
            "LucidIoCtrl.exe was not found:\n"
            f"{LUCID_IO_CTRL_EXE}"
        )

    if BRONKHORST_BAUDRATE <= 0:
        raise ValueError(
            "BRONKHORST_BAUDRATE must be greater than zero."
        )

    if BRONKHORST_NODE_ADDRESS < 0:
        raise ValueError(
            "BRONKHORST_NODE_ADDRESS must not be negative."
        )

    if BINARY_VALVE_CHANNEL < 0:
        raise ValueError(
            "BINARY_VALVE_CHANNEL must not be negative."
        )

    if LED_CHANNEL < 0:
        raise ValueError(
            "LED_CHANNEL must not be negative."
        )

    if DEFAULT_FLOW_SETPOINT_ML_MIN < 0:
        raise ValueError(
            "DEFAULT_FLOW_SETPOINT_ML_MIN must not be negative."
        )

    if MAXIMUM_ALLOWED_FLOW_ML_MIN <= 0:
        raise ValueError(
            "MAXIMUM_ALLOWED_FLOW_ML_MIN must be greater than zero."
        )

    if DEFAULT_FLOW_SETPOINT_ML_MIN > MAXIMUM_ALLOWED_FLOW_ML_MIN:
        raise ValueError(
            "DEFAULT_FLOW_SETPOINT_ML_MIN must not exceed "
            "MAXIMUM_ALLOWED_FLOW_ML_MIN."
        )

    if SAMPLE_INTERVAL_SECONDS <= 0:
        raise ValueError(
            "SAMPLE_INTERVAL_SECONDS must be greater than zero."
        )


def create_required_directories() -> None:
    MEASUREMENT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )
