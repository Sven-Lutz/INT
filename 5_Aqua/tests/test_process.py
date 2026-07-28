from __future__ import annotations

from config import (
    BINARY_VALVE_CHANNEL,
    BINARY_VALVE_CLOSED_STATE,
    BINARY_VALVE_OPEN_STATE,
    BRONKHORST_BAUDRATE,
    BRONKHORST_NODE_ADDRESS,
    BRONKHORST_PORT,
    CAPACITANCE_CHANNEL,
    CSV_DELIMITER,
    DATETIME_FORMAT,
    DEFAULT_FLOW_SETPOINT_ML_MIN,
    HUMIDITY_CHANNEL,
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
from control.water_process import WaterProcessController
from data.logger import CsvDataLogger
from data.repository import MeasurementRepository
from devices.bronkhorst import BronkhorstFlowController
from devices.lucid_ai4 import LucidAnalogInput
from devices.lucid_do import (
    BinaryValve,
    LedController,
    LucidDigitalOutput,
)


TEST_DURATION_SECONDS = 30.0


def main() -> None:
    validate_configuration()
    create_required_directories()

    lucid_outputs = LucidDigitalOutput(
        executable=LUCID_IO_CTRL_EXE,
        port=LUCID_DO_PORT,
    )

    controller = WaterProcessController(
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
        sample_interval_seconds=SAMPLE_INTERVAL_SECONDS,
        capacitance_channel=CAPACITANCE_CHANNEL,
        humidity_channel=HUMIDITY_CHANNEL,
    )

    controller.connect()

    try:
        summary = controller.start(
            flow_setpoint_ml_min=(
                DEFAULT_FLOW_SETPOINT_ML_MIN
            ),
            duration_seconds=TEST_DURATION_SECONDS,
            on_measurement=lambda m: print(
                f"Flow={m.flow_ml_min:.3f} ml/min | "
                f"Cap={m.capacitance_voltage_v:.5f} V | "
                f"Humidity={m.humidity_voltage_v:.5f} V"
            ),
        )
        print(summary)
    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()
