from __future__ import annotations

from config import (
    DEFAULT_VALVE_POSITION_PERCENT,
    create_required_directories,
    validate_configuration,
)
from main import build_controller, print_measurement


TEST_DURATION_SECONDS = 30.0


def main() -> None:
    validate_configuration()
    create_required_directories()

    controller = build_controller()
    controller.connect()

    try:
        summary = controller.start(
            valve_position_percent=(
                DEFAULT_VALVE_POSITION_PERCENT
            ),
            duration_seconds=TEST_DURATION_SECONDS,
            on_measurement=print_measurement,
        )
        print(summary)
    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()
