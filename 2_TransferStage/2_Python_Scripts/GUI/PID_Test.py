import time
import os

import pandas as pd
import matplotlib.pyplot as plt

from simple_pid import PID

from hardware.device_manager import DeviceManager
project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

device_manager = DeviceManager()
#writer = Configurator.WritingManager(project)
#config, _ = writer.read_yaml("both")
#valve = Configurator.Valve()
#OB1 = Configurator.PressureController(config)
#BFS = Configurator.FlowController()

flow_setpoint = 30000
tot_changed_vol = 10000

p_term = 0.9            # At 1.8 the p-term becomes unstable
i_term = 6            # At 8 oscillations start, but are still decreasing
d_term = 0.05

device_manager.select_container("10 Sample")
def main():

    device_manager.filling()                                            # Set valves in push state
    device_manager.start_pump()
    pid = PID(p_term, i_term, d_term, setpoint=flow_setpoint)   # PID controller is initialized, values have been manually found
    pid.output_limits = (-1000, 6000)                           # Limits for pressure are added, range is set by the hardware of the OB1

    data = [[0.], [0.], [0.], [0.], [0.]]           # Initialize data list

    start_time = time.time()  # Set start time
    timestamp = 0  # Timestamps is used for time tracking

    changed_volume = 0  # The changed_volume variable holds information of the current changed changed_volume of the operation

    while abs(changed_volume) < abs(tot_changed_vol):  # Stop if enough changed_volume has been changed

        flow_value = device_manager.get_flow()                     # Read set_flow
        pressure_value = device_manager.get_pressure()             # Read pressure
        delta_t = timestamp - data[0][-1]               # Calculate passed time since last reading
        delta_f = flow_value - data[2][-1]              # Calculate difference in set_flow since last reading

        data[0].append(timestamp)                       ###
        data[1].append(pressure_value)                  # Append data to list
        data[2].append(flow_value)                      #
        data[3].append(flow_setpoint)                   ###

        changed_volume += delta_t * flow_value / 60         # Calculate changed changed_volume, this line adds a rectangle, 60 adjusts the set_flow unit (ul/min)
        changed_volume += 1 / 2 * delta_t * delta_f / 60    # while this line adds a triangle, 60 adjusts the set_flow unit (ul/min)

        data[4].append(changed_volume)                      # Append changed_volume to list

        control_value = pid(flow_value)                     # Get new pressure value
        device_manager.set_pressure(p=control_value)                   # Set to new pressure

        timestamp = time.time() - start_time                # Calculate new timestamp

        print(f"Flow: {round(flow_value, 3)} µL/min\tSet Pressure: {control_value} mbar\tVolume: {changed_volume}")

    df = pd.DataFrame({"Time": data[0], "Pressure": data[1], "Flow": data[2], "Setpoint": data[3], "Volume": data[4]})
    df.to_json(r"C:\Users\Operator\TransferStage\5_Raw_Data\PID_test.json")


    device_manager.set_pressure(p=0)                                                           # Set pressure to zero
    device_manager.safe_state()                                                                # Set valves to venting

    plot_changes(df)
    return

def plot_changes(df):
    plt.plot(df["Time"], df["Pressure"], label="Pressure / [mbar]")
    plt.plot(df["Time"], df["Flow"], label="Flow / [ul/min]")
    plt.plot(df["Time"], df["Setpoint"], label="Flow Setpoint / [ul/min]")
    plt.plot(df["Time"], df["Volume"], label="Volume / [ul]")
    plt.legend()
    plt.show()
    return

if __name__ == "__main__":
    main()