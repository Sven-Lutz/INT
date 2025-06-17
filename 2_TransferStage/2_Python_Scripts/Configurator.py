import time

###################
###The Libraries###
###################

import yaml
import os
import Experiment

from state import pause_event, stop_event                               # Import the shared pause_event from state.py

from pyfirmata import Arduino
from Elveflow64 import *

##########################
###The global variables###
##########################


###################
###The functions###
###################

class Valve:
    """
    def: This class connects to valves via the arduino.
    """
    def __init__(self, experiment=None):
        print("Staring valve communication...")
        self.board = Arduino('COM3')                            # Connecting to the board, this is hardcoded
        self.experiment = experiment
        self.valve = {"V1": [10,12],                             # Valve 1 is used for venting. It is set to pin 10 in the arduino and connected with the LED at pin 12. NO-Valve
                     "V2": [11,13],                             # Valve 2 is used for switching between the water and waste bottles. It is set to pin 11 in the arduino and connected with the LED at pin 13
                     "V3": [9,8],                               # Valve 3 is used for blocking the set_flow line. It is set to pin 9 in the arduino and connected with the LED at pin 8. NC-Valve
                     }
        self.vent_pos()                                         # Set valves into the safe position
        print("Valve communication successfully started\n")
        return

    @property
    def temp(self):
        return self.experiment.temp  # Get the 'temp' dictionary from the experiment instance

    @temp.setter
    def temp(self, value):
        if isinstance(value, dict):  # If 'value' is a dictionary, update Exp.temp
            self.experiment.temp.update(value)  # Update existing dictionary with new values
        else:
            raise ValueError("temp must be a dictionary or dictionary-like object")

    def _switch_v(self, v, state):
        """
        def: This function switches the state of the valve
        :param v: String which indicates the name of the valve.
        :param state: State of the valve, it can be open or closed.
        :return: ---
        """
        print(f"{v}: {state}")
        self.board.digital[self.valve[v][0]].write(state)       # Changes the state of the valve 1 or 2.
        self.board.digital[self.valve[v][1]].write(state)       # Changes the state of the LED for visual feedback

        self.temp.update({v: state})
        print(f"Valves Changed: {self.temp}")
        return

    def vent_pos(self):
        """
        def: This function opens the venting valve.
             This state is considered as safe since the bottles are not under pressure.
        """
        self._switch_v("V1", 0)                         # Open venting valve
        self._switch_v("V3", 0)                         # Closing blocking valve
        return

    def suck_pos(self):
        """
        def: This function changes the valves to the sucking state,
             meaning that the waste water bottle is filled.
        """
        self._switch_v("V1", 1)                         # Close venting valve
        self._switch_v("V2", 0)                         # Switch to waste bottle
        self._switch_v("V3", 1)                         # Open blocking valve
        return

    def push_pos(self):
        """
        def: This function changes the valves to the sucking state,
             meaning that the waste water bottle is filled.
        """
        self._switch_v("V1", 1)                         # Close venting valve
        self._switch_v("V2", 1)                         # Switch to water bottle
        self._switch_v("V3", 1)                         # Open blocking valve
        return

    def block_pos(self):
        """
        def: This function closes the blocking valve
        """
        self._switch_v("V3",0)
        return

    def open_pos(self):
        """
        def. This function opens the blocking valve
        """
        self._switch_v("V3", 1)
        return

class PressureController:
    """
    def: This class connects to the OB1 pressure controller.
    """
    def __init__(self,config):
        print("Starting pressure controller communication...")
        self.Instr_ID = c_int32()
        self._initialize_device()
        self._load_calibration(config)
        print("Pressure controller  communication successfully started\n")
        return

    def _initialize_device(self):
        """
        def: This funciton initializes the OB1 device and store the instrument ID.
        """
        error = OB1_Initialization('02079BB9'.encode('ascii'), 5, 0, 0, 0, byref(self.Instr_ID))    #see User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            raise ConnectionError(f"ERROR: Unable to connect to OB1 device, error code: {error}")
        print(f"OB1 initialized with ID: {self.Instr_ID.value}")
        return

    def _load_calibration(self, config):
        """
        def: This function loads the calibration file path and initialize calibration array.
             The calibration_path is hardcoded in the script
        """
        config_path = os.path.join(config["Project Path"], "4_Config")              # Set the config path
        self.Calib = (c_double * 1000)()                                            # Calibration array with 1000 elements
        self.Calib_path = os.path.join(config_path, "Calib_latest.txt")             # Set the calibration path

        error = Elveflow_Calibration_Load(self.Calib_path.encode('ascii'), byref(self.Calib), 1000)     # Load the calibration
        if error != 0:
            print(f"WARNING: Calibration file could not be loaded, error code: {error}")

        self.set_pressure(0)                                                        # Set initial pressure to zero
        return

    def calibrate(self):
        """
        def: This function performs calibration and save it to the calibration file.
        """
        OB1_Calib(self.Instr_ID.value, self.Calib, 1000)
        error = Elveflow_Calibration_Save(self.Calib_path.encode('ascii'), byref(self.Calib), 1000)     # This creates a new calib file, make sure to conduct the calibration properly
        if error == 0:
            print(f"Calibration successfully saved to {self.Calib_path}")
        else:
            print(f"ERROR: Calibration save failed, error code: {error}")
        return

    def set_pressure(self, p=0):
        """
        def: This function sets the pressure at the pressure controller.
        :param p: Integer, which is the pressure value
        :return: ---
        """
        if p < -1000 or p > 6000:                                                               # Check if pressure is out of bounds
            raise ValueError("ERROR: PRESSURE OUT OF RANGE, choose within -1 to 6 bars.")

        set_channel = c_int32(1)                                                                # Convert channel (1) to c_int32, this has to be done, as the pressure controller is programmed in C
        set_pressure = c_double(float(p))                                                       # Converto pressure to c_double
        error = OB1_Set_Press(self.Instr_ID.value, set_channel, set_pressure, byref(self.Calib), 1000)

        if error != 0:
            print(f"ERROR: Pressure could not be set, error code: {error}")
        return


    def get_pressure(self):
        """
        def: This function reads the pressure of the controller
        """
        set_channel = c_int32(1)                                        # Convert channel (1) to c_int32, this has to be done, as the pressure controller is programmed in C
        get_pressure = c_double()                                       # Set pressure variable to a c_double
        error = OB1_Get_Press(self.Instr_ID.value, set_channel, 1, byref(self.Calib), byref(get_pressure), 1000)  # Acquire_data=1 -> read all the analog values
        if error != 0:
            print(f"ERROR: Unable to retrieve pressure, error code: {error}")
            return None
        return get_pressure.value

class FlowController:
    """
    def: This class connects to the BFS flow controller.
    """
    def __init__(self):
        print("Staring set_flow controller communication...")
        self.Instr_ID = c_int32()
        self._initialize_device()
        print("Flow controller communication successfully started")
        print("")
        return

    def _initialize_device(self):
        """
        def: This function initializes the BFS set_flow controller and retrieves liquid density for calibration.
        """
        error = BFS_Initialization("ASRL5::INSTR".encode('ascii'), byref(self.Instr_ID))            # See User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            raise ConnectionError(f"ERROR: Unable to establish connection, error code: {error}")
        print(f"BFS2 initialized with ID: {self.Instr_ID.value}")

        self._retrieve_density()                                                    # Get the density which has to be done in the beginning
        return

    def _retrieve_density(self):
        """
        def: This function retrieves and prints the liquid density for calibration purposes.
        """
        density = c_double(-1)
        error = BFS_Get_Density(self.Instr_ID.value, byref(density))  # Get density
        if error == 0:
            print(f"Density retrieved: {round(density.value, 3)} kg/m^3")
        else:
            print(f"WARNING: Unable to retrieve density, error code: {error}")
        return

    def get_flow(self):
        """
        def: This function read the set_flow of the sensor.
        :return: float which is the flow.value
        """
        flow = c_double(-1)                                                         # Convert the set_flow to c_double
        error = BFS_Get_Flow(self.Instr_ID.value, byref(flow))                      # Read the set_flow
        if error != 0:
            print(f"ERROR: Unable to read set_flow, error code: {error}")
            return None
        return flow.value

class ContainerSelector:
    def __init__(self,config):
        print("Starting container selector communication...")
        self.Instr_ID = c_int32()
        self._initialize_device()
        print("Pressure container selector  communication successfully started\n")
        return

    def _initialize_device(self):
        """
        def: This funciton initializes the OB1 device and store the instrument ID.
        """
        error = MUX_DRI_Initialization('ASRL10::INSTR'.encode('ascii'), byref(self.Instr_ID))    #see User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            raise ConnectionError(f"ERROR: Unable to connect to MUX device, error code: {error}")
        print(f"MUX initialized with ID: {self.Instr_ID.value}")
        return

    def select_container(self):
        print("Test")
        return


class WritingManager:
    """
    def: This class manages all the writing and reading processes.
    """
    def __init__(self, project):
        self.project = project                                      # Load the project path
        self.config_path = os.path.join(project, "4_Config")        # Load the temp path
        self.config_file = "config"                                 # Set the name of the config file
        self.temp_file = "temp"                                     # Set the name of the temp file
        self._initialize_files()                                    # Creates yaml files from the default
        return

    def _initialize_files(self):
        """
        def: This function initializes temp and temp YAML files, creating them if they don't exist.
        """
        self._create_yaml_file(self.config_file)                    # Create a config file
        self._create_yaml_file(self.temp_file)                      # Create a temp file
        return

    def _get_file_path(self, filename):
        """
        def: This function is a helper function to get the full path for a YAML file in the temp directory.
        :return: os.path.join(self.config_path, f'{filename}.yaml'): String which is the path to filename.yaml
        """
        return os.path.join(self.config_path, f"{filename}.yaml")

    def _create_yaml_file(self, filename):
        """
        def: this function creates a metadata file if it does not exist already
        :param filename: String, which is the name of the file
        :return: ---
        """
        path = self._get_file_path(filename)                                    # Create the path of the file
        print(path)

        if not os.path.exists(path):                                            # Check if the path exists
            default_path = self._get_file_path(f"{filename}_default")           # Get the default path
            if os.path.exists(default_path):
                with open(default_path, 'r') as df:                             # Read the default file
                    data = yaml.safe_load(df)
                print(data)
                with open(path, 'w') as f:                                      # Make a new file from the default file
                    yaml.safe_dump(data, f)
                print(f"{filename}.yaml has been created from the default configuration.")
            else:
                raise FileExistsError(f"ERROR FILE NOT FOUND: Default configuration for {filename}.yaml not found.")
        else:
            print(f"{filename}.yaml already exists.")
        return

    def read_yaml(self, which):
        """
        def: This function reads the metadata
        :param which: String, which holds the name of the specific metadata to be read.
        :return: data: Dict, which contains the metadata
                 path: String which contains the path of the metadata
        """
        if which not in {"config", "temp", "both"}:                                     # Check if the correct file should be read
            raise ValueError("Invalid file type: choose 'config', 'temp', or 'both'")

        if which == "both":                                                             # If both files should the read,
            temp_data, _ = self._load_yaml_data(self.temp_file)                         # then call this function again separately
            config_data, path = self._load_yaml_data(self.config_file)                  #
            config_data.update(temp_data)                                               # Combine both dicts
            return config_data, path

        return self._load_yaml_data(self.temp_file if which == "temp" else self.config_file)    # return the demanded file

    def _load_yaml_data(self, filename):
        """
        def: This function is a helper function to load YAML data and return it with its file path.
        """
        path = self._get_file_path(filename)                # Set the filename
        with open(path, 'r') as f:
            data = yaml.safe_load(f)                        # load the yaml
        return data, path                                   # return the data and its path

    def update_yaml(self, which=None, key=None, new_value=None):
        """
        def: This function updates the metadata.
        :param which: String, which holds the name of the specific metadata to be read.
        :param key: String, which holds the information of the dictionary key of which the value is changed
        :param new_value: Value, which sets the new value of the corresponding key
        :return: ---
        """
        if which not in {"temp", "config"}:
            raise ValueError("Invalid file type: choose 'temp' or 'config'")
        if key is None:
            raise ValueError("A valid key must be provided for update.")

        data, path = self.read_yaml(which)                                  # Read the metadata
        data[key] = new_value                                               # Update the specific key with the new value

        with open(path, 'w') as f:                                          # Write the updated YAML content back to the file
            yaml.safe_dump(data, f)
            f.close()
        print(f"{which}\t{key}: {new_value}")
        return

def main():
    """
    def: This function is the main function and is called if the script is started as the main script and not called by another script.
         It allows for debugging this script without changing other scripts.
    :return: ---
    """
    print("###########################################################################")
    print("Configurator.py is executed, make sure this is the script that should be run.")
    print("###########################################################################")

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = WritingManager(project)

    config, _ = w.read_yaml("both")
    pc = PressureController(config)
    pc.calibrate()
    return

if __name__ == "__main__":
    main()