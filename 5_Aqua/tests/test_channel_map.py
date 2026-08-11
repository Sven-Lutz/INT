from __future__ import annotations

import time

from config import (
    CAPACITANCE_CHANNEL,
    CAPACITANCE_FILLED_VALUE,
    CAPACITANCE_FULL_VALUE,
    CAPACITANCE_VALUE_OFFSET,
    CAPACITANCE_VALUE_PER_VOLT,
    CAPACITANCE_EMPTY_THRESHOLD,
    HUMIDITY_CHANNEL,
    HUMIDITY_VOLTAGE_AT_0_PERCENT,
    HUMIDITY_VOLTAGE_AT_100_PERCENT,
    LUCID_AI_PORT,
    LUCID_IO_CTRL_EXE,
    SAMPLE_INTERVAL_SECONDS,
    validate_configuration,
)
from control.empty_detection import EmptyDetectionSettings
from devices.lucid_ai4 import LucidAnalogInput
from devices.sensors import CapacitanceScaling, HumidityScaling


SAMPLE_COUNT = 60


def main() -> None:
    """Verifies the AI4 channel assignment end to end.

    Prints every raw channel voltage next to the converted process
    values, so a swapped capacitance/humidity wiring shows up
    immediately: covering or emptying the vessel must move the
    capacitance value, not the humidity value.
    """

    validate_configuration()

    ai4 = LucidAnalogInput(
        executable=LUCID_IO_CTRL_EXE,
        port=LUCID_AI_PORT,
    )

    capacitance_scaling = CapacitanceScaling(
        value_per_volt=CAPACITANCE_VALUE_PER_VOLT,
        offset=CAPACITANCE_VALUE_OFFSET,
        full_value=CAPACITANCE_FULL_VALUE,
    )
    humidity_scaling = HumidityScaling(
        voltage_at_0_percent=HUMIDITY_VOLTAGE_AT_0_PERCENT,
        voltage_at_100_percent=HUMIDITY_VOLTAGE_AT_100_PERCENT,
    )
    settings = EmptyDetectionSettings(
        empty_threshold=CAPACITANCE_EMPTY_THRESHOLD,
        filled_threshold=CAPACITANCE_FILLED_VALUE,
    )

    print(ai4.identify())
    print(
        f"Capacitance -> AI4 channel {CAPACITANCE_CHANNEL}\n"
        f"Humidity    -> AI4 channel {HUMIDITY_CHANNEL}\n"
    )

    for _ in range(SAMPLE_COUNT):
        readings = ai4.read_all_channel_voltages()
        voltages = {
            reading.channel: reading.voltage_v
            for reading in readings
        }

        raw = " | ".join(
            f"CH{channel}={voltage:.5f} V"
            for channel, voltage in sorted(voltages.items())
        )

        capacitance = capacitance_scaling.to_value(
            voltages.get(CAPACITANCE_CHANNEL)
        )
        humidity = humidity_scaling.to_percent(
            voltages.get(HUMIDITY_CHANNEL)
        )

        print(
            f"{raw}  ->  "
            f"Capacitance={capacitance:.3f} V "
            f"({settings.classify(capacitance).value}) | "
            f"Humidity={humidity:.1f} %"
        )

        time.sleep(SAMPLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
