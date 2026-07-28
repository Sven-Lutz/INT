from __future__ import annotations

import time

from config import (
    LUCID_AI_PORT,
    LUCID_IO_CTRL_EXE,
    SAMPLE_INTERVAL_SECONDS,
    validate_configuration,
)
from devices.lucid_ai4 import LucidAnalogInput


def main() -> None:
    validate_configuration()

    ai4 = LucidAnalogInput(
        executable=LUCID_IO_CTRL_EXE,
        port=LUCID_AI_PORT,
    )

    print(ai4.identify())

    for _ in range(60):
        readings = ai4.read_all_channel_voltages()
        print(
            " | ".join(
                f"CH{reading.channel}={reading.voltage_v:.5f} V"
                for reading in readings
            )
        )
        time.sleep(SAMPLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
