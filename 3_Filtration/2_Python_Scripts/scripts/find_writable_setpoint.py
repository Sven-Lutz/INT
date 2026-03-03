from __future__ import annotations
import time
from src.hardware.drivers.flow_sensor import FlowSensor, FlowSensorConfig

def main():
    cfg = FlowSensorConfig(port="COM5", address=3, baudrate=38400, channel=1, scale_mode="engineering")
    # Fokus auf proc=33 (engineering), kleine Range
    parm_range = range(0, 80)

    with FlowSensor(cfg) as fs:
        for parm in parm_range:
            proc = 33
            try:
                before = fs.read_parameter(proc, parm, "f")
            except Exception:
                continue

            target = before + 0.2
            try:
                fs.write_parameter(proc, parm, target, "f")
                time.sleep(0.15)
                after = fs.read_parameter(proc, parm, "f")
            except Exception:
                continue

            if abs(after - target) < 0.05:
                print(f"WRITABLE HIT proc={proc} parm={parm} before={before} after={after}")
                # restore
                try:
                    fs.write_parameter(proc, parm, before, "f")
                except Exception:
                    pass

if __name__ == "__main__":
    main()
