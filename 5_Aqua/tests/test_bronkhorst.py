from __future__ import annotations

import time

from config import (
    BRONKHORST_BAUDRATE,
    BRONKHORST_NODE_ADDRESS,
    BRONKHORST_PORT,
    validate_configuration,
)
from devices.bronkhorst import BronkhorstFlowController


def main() -> None:
    validate_configuration()

    bronkhorst = BronkhorstFlowController(
        port=BRONKHORST_PORT,
        node_address=BRONKHORST_NODE_ADDRESS,
        baudrate=BRONKHORST_BAUDRATE,
    )

    bronkhorst.connect()

    try:
        for _ in range(20):
            print(
                f"Flow={bronkhorst.read_flow_ml_min():.3f} ml/min | "
                f"Temp={bronkhorst.read_temperature_c():.2f} °C | "
                f"Alarm={bronkhorst.read_alarm_info()}"
            )
            time.sleep(0.5)
    finally:
        bronkhorst.force_valve_closed()
        bronkhorst.disconnect()


if __name__ == "__main__":
    main()
