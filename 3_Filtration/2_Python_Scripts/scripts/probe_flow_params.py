from __future__ import annotations

from src.hardware.drivers.flow_sensor import FlowSensor, FlowSensorConfig


def main() -> None:
    cfg = FlowSensorConfig(
        port="COM5",
        address=3,
        baudrate=38400,
        channel=1,
        meas=(33, 0),
        setp=(33, 3),
        scale_mode="engineering",
    )

    known = [
        ("Fmeasure", 33, 0, "f"),
        ("Fsetpoint", 33, 3, "f"),
        ("Temperature", 33, 7, "f"),
    ]

    with FlowSensor(cfg) as fs:
        for name, proc, parm, vt in known:
            v = fs.read_parameter(proc, parm, vt)
            print(f"{name:12s} proc={proc:3d} parm={parm:3d} ({vt}) -> {v}")


if __name__ == "__main__":
    main()
