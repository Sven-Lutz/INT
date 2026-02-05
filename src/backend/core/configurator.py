###################
###The Libraries###
###################

import yaml
import os

from utils import rly02.py
#import rly02
#from Elveflow64 import *
##########################
###The Global Variables###
##########################


#################
###The Classes###
#################

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

class FlowSensor:
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
        error = BFS_Initialization("COM5".encode('ascii'), byref(self.Instr_ID))            # See User Guide to determine regulator types and NIMAX to determine the instrument name
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
        error = BFS_Get_Density(self.Instr_ID.value, byref(density))                # Get density
        if error == 0:
            print(f"Density retrieved: {round(density.value,3)} kg/m^3")
        else:
            print(f"WARNING: Unable to retrieve density, error code: {error}")
        return


def main():
    """
    def: This function is the main function and is called if the script is started as the main script and not called by another script.
         It allows for debugging this script without changing other scripts.
    :return: ---
    """
    print("###########################################################################")
    print("configurator.py is executed, make sure this is the script that should be run.")
    print("###########################################################################")

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = WritingManager(project)

    config, _ = w.read_yaml("both")
    #v = Valve()
    #v.all_on()
    pc = PressureController(config)
    #pc.set_pressure(0)
    #pc.calibrate()
    #pc.calibrate()

    return

if __name__ == "__main__":
    main()