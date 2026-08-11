from __future__ import annotations

from config import (
    BINARY_VALVE_CHANNEL,
    BINARY_VALVE_CLOSED_STATE,
    BINARY_VALVE_OPEN_STATE,
    BRONKHORST_BAUDRATE,
    BRONKHORST_NODE_ADDRESS,
    BRONKHORST_PORT,
    CAPACITANCE_CHANNEL,
    CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES,
    CAPACITANCE_EMPTY_STOP_ENABLED,
    CAPACITANCE_EMPTY_THRESHOLD,
    CAPACITANCE_FILLED_VALUE,
    CAPACITANCE_FULL_VALUE,
    CAPACITANCE_VALUE_OFFSET,
    CAPACITANCE_VALUE_PER_VOLT,
    CSV_DELIMITER,
    DATETIME_FORMAT,
    DEFAULT_VALVE_POSITION_PERCENT,
    HUMIDITY_CHANNEL,
    HUMIDITY_VOLTAGE_AT_0_PERCENT,
    HUMIDITY_VOLTAGE_AT_100_PERCENT,
    LED_CHANNEL,
    LED_OFF_STATE,
    LED_ON_STATE,
    LUCID_AI_PORT,
    LUCID_DO_PORT,
    LUCID_IO_CTRL_EXE,
    MEASUREMENT_DIRECTORY,
    MEASUREMENT_FILE_PREFIX,
    SAMPLE_INTERVAL_SECONDS,
    create_required_directories,
    validate_configuration,
)
from control.empty_detection import (
    EmptyDetectionSettings,
    EmptyDetector,
)
from control.water_process import WaterProcessController
from data.logger import CsvDataLogger
from data.models import SystemMeasurement
from data.repository import MeasurementRepository
from devices.bronkhorst import BronkhorstFlowController
from devices.lucid_ai4 import LucidAnalogInput
from devices.lucid_do import (
    BinaryValve,
    LedController,
    LucidDigitalOutput,
)
from devices.sensors import CapacitanceScaling, HumidityScaling


# Upper bound for a drain run. The run normally ends earlier, as soon as
# the capacitance sensor reports an empty vessel.
MAXIMUM_RUN_DURATION_SECONDS = 900.0


def build_empty_detector() -> EmptyDetector:
    return EmptyDetector(
        EmptyDetectionSettings(
            empty_threshold=CAPACITANCE_EMPTY_THRESHOLD,
            filled_threshold=CAPACITANCE_FILLED_VALUE,
            consecutive_samples=(
                CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES
            ),
            enabled=CAPACITANCE_EMPTY_STOP_ENABLED,
        )
    )


def build_controller() -> WaterProcessController:
    lucid_outputs = LucidDigitalOutput(
        executable=LUCID_IO_CTRL_EXE,
        port=LUCID_DO_PORT,
    )

    return WaterProcessController(
        bronkhorst=BronkhorstFlowController(
            port=BRONKHORST_PORT,
            node_address=BRONKHORST_NODE_ADDRESS,
            baudrate=BRONKHORST_BAUDRATE,
        ),
        binary_valve=BinaryValve(
            controller=lucid_outputs,
            channel=BINARY_VALVE_CHANNEL,
            open_state=BINARY_VALVE_OPEN_STATE,
            closed_state=BINARY_VALVE_CLOSED_STATE,
        ),
        led=LedController(
            controller=lucid_outputs,
            channel=LED_CHANNEL,
            on_state=LED_ON_STATE,
            off_state=LED_OFF_STATE,
        ),
        analog_inputs=LucidAnalogInput(
            executable=LUCID_IO_CTRL_EXE,
            port=LUCID_AI_PORT,
        ),
        logger=CsvDataLogger(
            directory=MEASUREMENT_DIRECTORY,
            delimiter=CSV_DELIMITER,
            file_prefix=MEASUREMENT_FILE_PREFIX,
            datetime_format=DATETIME_FORMAT,
        ),
        repository=MeasurementRepository(),
        empty_detector=build_empty_detector(),
        capacitance_scaling=CapacitanceScaling(
            value_per_volt=CAPACITANCE_VALUE_PER_VOLT,
            offset=CAPACITANCE_VALUE_OFFSET,
            full_value=CAPACITANCE_FULL_VALUE,
        ),
        humidity_scaling=HumidityScaling(
            voltage_at_0_percent=(
                HUMIDITY_VOLTAGE_AT_0_PERCENT
            ),
            voltage_at_100_percent=(
                HUMIDITY_VOLTAGE_AT_100_PERCENT
            ),
        ),
        sample_interval_seconds=SAMPLE_INTERVAL_SECONDS,
        capacitance_channel=CAPACITANCE_CHANNEL,
        humidity_channel=HUMIDITY_CHANNEL,
    )


def print_measurement(measurement: SystemMeasurement) -> None:
    capacitance = (
        f"{measurement.capacitance_value:.3f} V"
        if measurement.capacitance_value is not None
        else "—"
    )
    humidity = (
        f"{measurement.humidity_percent:.1f} %"
        if measurement.humidity_percent is not None
        else "—"
    )

    print(
        f"Flow={measurement.flow_ml_min:.3f} ml/min | "
        f"Cap={capacitance} ({measurement.capacitance_state}) | "
        f"Humidity={humidity}"
    )


def main() -> int:
    controller = None

    try:
        validate_configuration()
        create_required_directories()

        controller = build_controller()
        controller.connect()

        summary = controller.start(
            valve_position_percent=(
                DEFAULT_VALVE_POSITION_PERCENT
            ),
            duration_seconds=MAXIMUM_RUN_DURATION_SECONDS,
            on_measurement=print_measurement,
        )

        print(summary)
        return 0

    except KeyboardInterrupt:
        if controller is not None:
            controller.request_stop(
                "Process interrupted by operator."
            )
        return 130

    finally:
        if controller is not None:
            controller.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
