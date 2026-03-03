from __future__ import annotations

from src.hardware.drivers.flow_sensor import FlowSensor, FlowSensorConfig

def main():
    cfg = FlowSensorConfig(port="COM5", address=3, baudrate=38400, channel=1)

    # Minimal: bekannte ProPar-Parameter
    known = [
        ("Measure", 1, 0, "i"),
        ("Setpoint", 1, 1, "i"),
        ("ControlMode", 1, 4, "i"),
        ("AlarmInfo", 1, 20, "i"),
        ("Fmeasure", 33, 0, "f"),
        ("Fsetpoint", 33, 3, "f"),
        ("Temperature", 33, 7, "f"),
    ]

    with FlowSensor(cfg) as fs:
        for name, proc, parm, vt in known:
            try:
                v = fs.read_parameter(proc, parm, vt)  # falls eure API so heißt
                print(f"{name:12s} proc={proc:3d} parm={parm:3d} ({vt}) -> {v}")
            except Exception as e:
                print(f"{name:12s} FAILED: {e!r}")

if __name__ == "__main__":
    main()
