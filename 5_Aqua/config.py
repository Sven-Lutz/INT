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

# These two constants are the single source of truth for the complete
# signal chain:
#
#   AI4 channel -> device read -> SystemMeasurement -> CSV -> GUI -> chart
#
# Nothing downstream re-derives a channel number, so a swapped sensor is
# corrected here and nowhere else.
CAPACITANCE_CHANNEL = 0
HUMIDITY_CHANNEL = 1


# =============================================================================
# SENSOR SCALING
# =============================================================================

# The AI4 driver reports a raw voltage. A separate scaled capacitance
# process value is derived from it; the physical transfer function has
# not yet been confirmed during commissioning.
#
#   capacitance_value [scaled] = raw_voltage * CAPACITANCE_VALUE_PER_VOLT
#                                + CAPACITANCE_VALUE_OFFSET
#
# The defaults pass the numeric reading through unchanged. This does not
# establish that a configured value near 25 is a physical 25 V signal.
CAPACITANCE_VALUE_PER_VOLT = 1.0
CAPACITANCE_VALUE_OFFSET = 0.0

# Current commissioning estimates: roughly 25 scaled units while water
# is present and roughly 0 once the vessel has run empty.
CAPACITANCE_FULL_VALUE = 25.0

# Above this scaled value the vessel is reported as FILLED, below the
# empty threshold as EMPTY, and in between as DRAINING.
CAPACITANCE_FILLED_VALUE = 12.5

# The humidity sensor is read as a voltage and converted to % relative
# humidity by a linear mapping between these two support points.
HUMIDITY_VOLTAGE_AT_0_PERCENT = 0.0
HUMIDITY_VOLTAGE_AT_100_PERCENT = 10.0


# =============================================================================
# PROCESS SETTINGS
# =============================================================================

# Direct valve position is the default operator control method. Closed-loop
# flow target remains available as the alternative control method per run.
DEFAULT_VALVE_POSITION_PERCENT = 100.0

SAMPLE_INTERVAL_SECONDS = 0.5
MAXIMUM_ALLOWED_FLOW_ML_MIN = 200.0

# Default for the operator-selectable closed-loop Flow Target control method.
DEFAULT_FLOW_SETPOINT_ML_MIN = 100.0
DEFAULT_TARGET_VOLUME_ML = 500.0
TARGET_VOLUME_STOP_ENABLED = False


# =============================================================================
# EMPTY DETECTION — CAPACITANCE
# =============================================================================

# Draining always runs from "full" towards "empty", so the only relevant
# condition is capacitance <= threshold, expressed in scaled units.
CAPACITANCE_EMPTY_THRESHOLD = 5.0

# Number of consecutive samples below the threshold before the process is
# stopped. Debounces single noisy readings.
CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES = 3

CAPACITANCE_EMPTY_STOP_ENABLED = True


# =============================================================================
# SAFETY LIMITS
# =============================================================================

# Keep disabled until the humidity sensor has been calibrated.
# A rising humidity indicates a leak and therefore remains an upper limit.
CRITICAL_HUMIDITY_PERCENT: float | None = None


# =============================================================================
# GUI LAYOUT
# =============================================================================

# Initial split between the control panel and the plot area (about 1/3
# to 2/3). The operator can still drag the splitter afterwards.
GUI_SPLITTER_SIZES = (480, 960)
GUI_LEFT_PANEL_MINIMUM_WIDTH = 380


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

    if BINARY_VALVE_CHANNEL == LED_CHANNEL:
        raise ValueError(
            "BINARY_VALVE_CHANNEL and LED_CHANNEL must differ."
        )

    if CAPACITANCE_CHANNEL < 0 or HUMIDITY_CHANNEL < 0:
        raise ValueError(
            "AI4 channel numbers must not be negative."
        )

    if CAPACITANCE_CHANNEL == HUMIDITY_CHANNEL:
        raise ValueError(
            "CAPACITANCE_CHANNEL and HUMIDITY_CHANNEL must differ. "
            "Both sensors cannot share one AI4 channel."
        )

    if not 0.0 <= DEFAULT_VALVE_POSITION_PERCENT <= 100.0:
        raise ValueError(
            "DEFAULT_VALVE_POSITION_PERCENT must be between "
            "0 and 100."
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

    if DEFAULT_TARGET_VOLUME_ML <= 0:
        raise ValueError(
            "DEFAULT_TARGET_VOLUME_ML must be greater than zero."
        )

    if SAMPLE_INTERVAL_SECONDS <= 0:
        raise ValueError(
            "SAMPLE_INTERVAL_SECONDS must be greater than zero."
        )

    if CAPACITANCE_EMPTY_THRESHOLD < 0:
        raise ValueError(
            "CAPACITANCE_EMPTY_THRESHOLD must not be negative."
        )

    if CAPACITANCE_FILLED_VALUE <= CAPACITANCE_EMPTY_THRESHOLD:
        raise ValueError(
            "CAPACITANCE_FILLED_VALUE must be greater than "
            "CAPACITANCE_EMPTY_THRESHOLD."
        )

    if CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES < 1:
        raise ValueError(
            "CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES must be at "
            "least 1."
        )

    if (
        HUMIDITY_VOLTAGE_AT_0_PERCENT
        == HUMIDITY_VOLTAGE_AT_100_PERCENT
    ):
        raise ValueError(
            "HUMIDITY_VOLTAGE_AT_0_PERCENT and "
            "HUMIDITY_VOLTAGE_AT_100_PERCENT must differ."
        )


def create_required_directories() -> None:
    MEASUREMENT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )
