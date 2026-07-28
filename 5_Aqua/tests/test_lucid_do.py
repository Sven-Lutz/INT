from __future__ import annotations

import time

from config import (
    BINARY_VALVE_CHANNEL,
    BINARY_VALVE_CLOSED_STATE,
    BINARY_VALVE_OPEN_STATE,
    LED_CHANNEL,
    LED_OFF_STATE,
    LED_ON_STATE,
    LUCID_DO_PORT,
    LUCID_IO_CTRL_EXE,
    validate_configuration,
)
from devices.lucid_do import (
    BinaryValve,
    LedController,
    LucidDigitalOutput,
)


TEST_HOLD_SECONDS = 3.0


def main() -> None:
    validate_configuration()

    controller = LucidDigitalOutput(
        executable=LUCID_IO_CTRL_EXE,
        port=LUCID_DO_PORT,
    )

    binary_valve = BinaryValve(
        controller=controller,
        channel=BINARY_VALVE_CHANNEL,
        open_state=BINARY_VALVE_OPEN_STATE,
        closed_state=BINARY_VALVE_CLOSED_STATE,
    )

    led = LedController(
        controller=controller,
        channel=LED_CHANNEL,
        on_state=LED_ON_STATE,
        off_state=LED_OFF_STATE,
    )

    try:
        binary_valve.close()
        led.off()

        binary_valve.open()
        print("Binary valve open:", binary_valve.is_open())
        time.sleep(TEST_HOLD_SECONDS)

        binary_valve.close()
        print("Binary valve open:", binary_valve.is_open())

        led.on()
        print("LED on:", led.is_on())
        time.sleep(TEST_HOLD_SECONDS)

        led.off()
        print("LED on:", led.is_on())

    finally:
        led.off()
        binary_valve.close()


if __name__ == "__main__":
    main()
