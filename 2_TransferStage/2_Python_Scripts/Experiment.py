###################
###The Libraries###
###################

import Configurator
import time
import os
import random

import matplotlib.pyplot as plt
import pandas as pd
import rly02 as vac_pump

from simple_pid import PID
from state import pause_event, stop_event                               # Import the shared pause_event from state.py

#################
###The Classes###
#################

class Experimentator:
    """
    def: This class manages the experiment protocol.
    """
    def __init__(self, writer):
        self.writer = writer

        self.config, _ = self.writer.read_yaml("both")
        self.temp, _ = self.writer.read_yaml("temp")                            # Read temp.yaml, since some variable have to be initialized from the beginning


        self.valve = Configurator.Valve(self)
        self.OB1 = Configurator.PressureController(self.config)
        self.BFS = Configurator.FlowController()


        self.init_vol = None
        self.set_flow = None

        self.max_vol = self.config["Maximum Volume"]
        self.p_term = self.config["P Term"]
        self.i_term = self.config["I Term"]
        self.d_term = self.config["D Term"]

        return

    def __del__(self):
        vac_pump.turn_off()
        return

    def setup_experiment(self):
        """
        def: This function sets some initial parameters. It is called every time an operation is performed,
             since each operation has different initial values.
        """
        self.temp, _ = self.writer.read_yaml("temp")                            # Read temp.yaml
        self.init_vol = self.temp["Current Vessel Volume"]                      # Get the initial volume
        self.set_flow = self.temp["Set Flow"]                                   # Get the set flow
        print(f"Current volume in vessel: {round(self.init_vol, 3)} uL")
        return

    def simulate_amount(self, operation=None, tot_changed_vol=None):
        if operation not in ["push", "suck"]:                                               # Only pushing or sucking is allowed
            raise ValueError("Operation must be 'push' or 'suck'")                          # If this is triggered then there is a bug somewhere

        self.setup_experiment()                                                             # Set up the experiment before running it
        flow_setpoint = self.set_flow if operation == "push" else -self.set_flow                                        # Calculate the flow setpoint
        final_vol = self.init_vol + tot_changed_vol if operation == "push" else self.init_vol - tot_changed_vol         # Calculate the final volume
        self.temp.update({"Final Volume": final_vol})                                                                   # Update the final volume in the temp dict

        if self.temp["Bottle Volume"]*1000-tot_changed_vol<150000:                                                      # Make sure there is enough water left in the bottles
            raise ValueError(f"VOLUME IN BOTTLE TOO SMALL: remaining volume is {self.temp['Bottle Volume']}. Refill water bottle and empty waste bottle.")

        if operation == "suck" and final_vol < 0:                                                                       # Make sure there is enough water left in the vessel
            raise ValueError(f"REMAINING VOLUME WILL BE NEGATIVE: Max removal is {self.init_vol} µL")
        elif operation == "push" and final_vol > self.max_vol:                                                          # Make sure the is enough volume left in the vessel
            raise ValueError(f"REMAINING VOLUME EXCEEDS LIMIT: Max addition is {self.max_vol - self.init_vol} µL")

        self.valve.push_pos() if operation == "push" else self.valve.suck_pos()

        data = {"Time": [0.], "Pressure": [0.], "Flow": [0.], "Setpoint": [flow_setpoint], "Volume": [self.init_vol]}   # Initialize the data dataframe
        start_time = time.time()                                                                                        # get the starting point of the measurement

        changed_volume = 0                                                          # set some variables to zero
        flow_value = 0

        print(f"######################")                                            # Print experiment stats
        print(f"###Transfer Stats###")
        print(f"######################")
        print(f"Operation: {self.temp['Operation']}")
        print(f"Change: {operation}")
        print(f"Volume in Vessel: {self.init_vol}")
        print(f"Volume to be changed: {tot_changed_vol}")
        print(f"Volume after transfer: {final_vol}")
        print(f"Flow: {self.set_flow}")
        print(f"######################")

        while abs(changed_volume) < abs(tot_changed_vol):                           # Stop if enough changed_volume has been changed
            if stop_event.is_set():                                                 # Check if the experiment is aborted
                print("Stopping")
                return
            while pause_event.is_set():                                             # Check if the experiment is paused
                time.sleep(0.1)
                if stop_event.is_set():
                    print("Stopping")
                    return

            flow_value = round(random.uniform(100, 300), 2) * 100                                       # Read set_flow
            pressure_value = round(random.uniform(0.2, 0.6), 2)                                # Read pressure
            timestamp = time.time() - start_time

            delta_t = timestamp - (data["Time"][-1] if data["Time"] else 0)         # Calculate the time passed
            delta_f = flow_value - (data["Flow"][-1] if data["Flow"] else 0)        # Calculate the flow difference

            delta_v = (delta_t * flow_value + 0.5 * delta_t * delta_f) / 60         # This is the numerical integration of the volume, it uses rectangles and triangles. The volume has to be adjusted for µL/min
            changed_volume += delta_v                                               # Calculate the changed volume

            data["Time"].append(timestamp)                                          # Add data to the dataframe
            data["Pressure"].append(pressure_value)
            data["Flow"].append(flow_value)
            data["Setpoint"].append(flow_setpoint)
            data["Volume"].append(self.init_vol + changed_volume)

            self.temp.update({"Current Flow":           flow_value,                                         # update the temp dict
                              "Current Pressure":       pressure_value,
                              "Current Vessel Volume":  self.init_vol + changed_volume,
                              "Remaining Volume":       abs(tot_changed_vol)- abs(changed_volume),
                              "Bottle Volume":          self.temp["Bottle Volume"]-abs(delta_v/1000)})

            print(f"Flow: {round(flow_value, 3)} µL/min\tCurrent Pressure: {pressure_value} mbar\tVolume: {round(changed_volume,3)}")
            print(self.temp)
            time.sleep(0.1)
        df = pd.DataFrame(data)
        #df.to_json(r"C:\Users\Operator\TransferStage\5_Raw_Data\Remove_Water.json")                                # Store the experimental data

        self.init_vol += changed_volume
        self.valve.vent_pos()                                                                                       # Set valves to venting
        print(f"Final Volume in Vessel: {round(self.temp['Current Vessel Volume'], 3)} uL")

        self.valve.vent_pos()                                                                                       # Set valves to safe position

        print("Process successfully finished")
        print(self.temp)
        return

    def change_amount(self, operation=None, tot_changed_vol=None):
        """
        def: Connects to the Pressure Controller and Flow Sensor and changes the amount of water in the setup. The PID feedback loop controlls the set_flow
        :param operation: String, which gives the type of operation, can be "push" or "suck".
        :param tot_changed_vol: positive Integer, total changed_volume to be changed in uL
        :return: ---
        """
        if operation not in ["push", "suck"]:                                               # Only pushing or sucking is allowed
            raise ValueError("Operation must be 'push' or 'suck'")                          # If this is triggered then there is a bug somewhere

        vac_pump.turn_on()                                                                                              # Turns on the vacuum pump

        flow_setpoint = self.set_flow if operation == "push" else -self.set_flow                                        # Calculate the flow setpoint
        final_vol = self.init_vol + tot_changed_vol if operation == "push" else self.init_vol - tot_changed_vol         # Calculate the final volume
        self.temp.update({"Final Volume": final_vol})                                                                   # Update the final volume in the temp dict

        if self.temp["Bottle Volume"]*1000-tot_changed_vol<150000:                                                      # Make sure there is enough water left in the bottles
            raise ValueError(f"VOLUME IN BOTTLE TOO SMALL: remaining volume is {self.temp['Bottle Volume']*1000-tot_changed_vol}. Refill water bottle and empty waste bottle.")

        if operation == "suck" and final_vol < 0:                                                                       # Make sure there is enough water left in the vessel
            raise ValueError(f"REMAINING VOLUME WILL BE NEGATIVE: Max removal is {self.init_vol} µL")
        elif operation == "push" and final_vol > self.max_vol:                                                          # Make sure the is enough volume left in the vessel
            raise ValueError(f"REMAINING VOLUME EXCEEDS LIMIT: Max addition is {self.max_vol - self.init_vol} µL")

        self.valve.push_pos() if operation == "push" else self.valve.suck_pos()

        pid = PID(self.p_term, self.i_term, self.d_term, setpoint=flow_setpoint)                                        # PID controller is initialized, values have been manually found
        pid.output_limits = (-1000, 6000)                                                                               # Limits for pressure are added, range is set by the hardware of the OB1

        data = {"Time": [0.], "Pressure": [0.], "Flow": [0.], "Setpoint": [flow_setpoint], "Volume": [self.init_vol]}   # Initialize the data dataframe
        start_time = time.time()                                                                                        # get the starting point of the measurement

        changed_volume = 0                                                          # set some variables to zero
        flow_value = 0

        print(f"######################")                                            # Print experiment stats
        print(f"###Transfer Stats###")
        print(f"######################")
        print(f"Operation: {self.temp['Operation']}")
        print(f"Change: {operation}")
        print(f"Volume in Vessel: {self.init_vol}")
        print(f"Volume to be changed: {tot_changed_vol}")
        print(f"Volume after transfer: {final_vol}")
        print(f"Flow: {self.set_flow}")
        print(f"######################")

        while abs(changed_volume) < abs(tot_changed_vol):                           # Stop if enough changed_volume has been changed
            if stop_event.is_set():                                                 # Check if the experiment is aborted
                print("Stopping")
                return
            while pause_event.is_set():                                             # Check if the experiment is paused
                time.sleep(0.1)
                if stop_event.is_set():
                    print("Stopping")
                    return

            flow_value = self.BFS.get_flow()                                        # Read set_flow
            pressure_value = self.OB1.get_pressure()                                # Read pressure
            timestamp = time.time() - start_time

            delta_t = timestamp - (data["Time"][-1] if data["Time"] else 0)         # Calculate the time passed
            delta_f = flow_value - (data["Flow"][-1] if data["Flow"] else 0)        # Calculate the flow difference

            delta_v = (delta_t * flow_value + 0.5 * delta_t * delta_f) / 60         # This is the numerical integration of the volume, it uses rectangles and triangles. The volume has to be adjusted for µL/min
            changed_volume += delta_v                                               # Calculate the changed volume

            data["Time"].append(timestamp)                                          # Add data to the dataframe
            data["Pressure"].append(pressure_value)
            data["Flow"].append(flow_value)
            data["Setpoint"].append(flow_setpoint)
            data["Volume"].append(self.init_vol + changed_volume)

            control_value = pid(flow_value)                                                                 # Get new pressure value
            self.OB1.set_pressure(p=control_value)                                                          # Set to new pressure

            self.temp.update({"Current Flow":           flow_value,                                         # update the temp dict
                              "Current Pressure":       pressure_value,
                              "Current Vessel Volume":  self.init_vol + changed_volume,
                              "Remaining Volume":       abs(tot_changed_vol)- abs(changed_volume)})
            if operation == "push":
                self.temp.update({"Bottle Volume": self.temp["Bottle Volume"]-abs(delta_v/1000)})
            #print(f"Flow: {round(flow_value, 3)} µL/min\tSet Pressure: {control_value} mbar\t Current Pressure: {pressure_value} mbar\tVolume: {round(changed_volume,3)}")

        df = pd.DataFrame(data)
        #df.to_json(r"C:\Users\Operator\TransferStage\5_Raw_Data\Remove_Water.json")                                # Store the experimental data

        self.init_vol += changed_volume
        self.OB1.set_pressure(p=0)                                                                                  # Set pressure to zero
        self.valve.vent_pos()                                                                                       # Set valves to venting
        start_time = time.time()
        while abs(flow_value) > 400:                                                                                # Vent bottles until no pressure is left
            flow_value = self.BFS.get_flow()                                                                        # Read set_flow

            print(f"Stabilizing set_flow below 400 µL/min. Current set_flow: {round(flow_value, 3)} µL/min")
            time.sleep(0.1)                                                                                         # Wait a little bit

        print(f"Final Volume in Vessel: {round(self.temp['Current Vessel Volume'], 3)} uL")

        self.valve.vent_pos()                                                                                       # Set valves to safe position
        vac_pump.turn_off()
        #self.plot_changes(df)
        return

    def plot_changes(self, df):
        """
        def: This function plots the data of the measurement.
        """
        plt.plot(df["Time"], df["Pressure"], label="Pressure / [mbar]")
        plt.plot(df["Time"], df["Flow"], label="Flow / [ul/min]")
        plt.plot(df["Time"], df["Setpoint"], label="Flow Setpoint / [ul/min]")
        plt.plot(df["Time"], df["Volume"], label="Volume / [ul]")
        plt.legend()
        plt.show()
        return

    def fill(self):
        """
        def: This function will fill the vessel completely.
        """
        self.setup_experiment()
        fillable_vol = self.max_vol-self.init_vol                       # Calculate the fillable volume
        self.change_amount("push", fillable_vol)               # Fill the vessel completely
        print("SUCCESS: Vessel completely filled")
        return

    def attachment(self):
        """
        def: This function will change the volume to the attachment state.
             It can add and remove volume accordingly.
        """
        self.setup_experiment()
        attachment_vol = self.config["Attachment Volume"]                               # Get the volume of the attachment state
        fillable_vol = attachment_vol - self.init_vol                                   # Calculate fillable volume
        self.change_amount("push" if fillable_vol > 0 else "suck", abs(fillable_vol))   # Determine if water is added or removed
        print("SUCCESS: Attachment process can know begin")
        return

    def empty(self):
        """
        def: This function removes the water of the vessel completely.
        """
        self.setup_experiment()
        fillable_vol = self.init_vol-self.temp["Safety Volume"]                                               # Calculate fillable volume and reduce it by a security margin to avoid bubbles
        self.change_amount("suck", fillable_vol)                               # Empty vessel
        print("SUCCESS: Vessel completely emptied")
        return

    def remove(self):
        """
        def: This function will remove a small amount of water from the setup.
        """
        self.setup_experiment()
        change_vol = self.config["Small Volume"]                                        # Get the small volume
        self.change_amount("suck", change_vol)                                 # Remove the small volume
        print("SUCCESS: Volume removed")
        return

    def add(self):
        """
        def: This function will add a small amount of water to the setup.
        """
        self.setup_experiment()
        change_vol = self.config["Small Volume"]                                        # Get the small volume
        self.change_amount("push", change_vol)                                 # Add volume
        print("SUCCESS: Volume added")
        return

    def pause(self):
        """
        def: This function toggles the pause state and thus changes the blocking valve.
        """
        if pause_event.is_set():                                                        # If the process is paused the valve should block the tube
            self.valve.block_pos()
            self.OB1.set_pressure(0)                                                    # The pressure is set to zero to be safe.
            vac_pump.turn_off()                                                         # Remember, there is still pressure in the bottles and this is not a 'safe' state
                                                                                        # The safe state is the venting_pos
        else:
            self.valve.open_pos()                                                       # If the process is resumed the valve should open again
            vac_pump.turn_on()
        return

    def vent(self):
        """
        def: This function moves the setup into the safe state and aborts all ongoing measurements.
        """
        stop_event.set()

        self.valve.vent_pos()
        self.OB1.set_pressure(0)        # The pressure is set to zero to be safe.
        return

    def pva_waiting(self):

        waiting_time_sec = self.config["PVA Waiting Time"] * 60  # The value is stored in minutes, but we need seconds thus the factor
        start_time = time.time()

        while time.time() - start_time < waiting_time_sec:
            delta = time.time() - start_time
            self.temp.update({"Remaining PVA Time": waiting_time_sec - delta})  # Update the temp
            time.sleep(0.1)

        self.temp.update({"Remaining PVA Time": 0})  # Set the remaining time to zero, the loop may not excaclty go to zero
        return

def main():
    """
    def: This function is the main function and is called if the script is started as the main script and not called by another script.
         It allows for debugging this script without changing other scripts.
    """
    print("###########################################################################")
    print("Experiment.py is executed, make sure this is the script that should be run.")
    print("###########################################################################")

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return

if __name__ == "__main__":
    main()