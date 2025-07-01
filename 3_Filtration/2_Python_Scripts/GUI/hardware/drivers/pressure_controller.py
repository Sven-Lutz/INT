###################
###The Libraries###
###################

import os
import logging

try:
    from  Elveflow64 import *
except ImportError:
    Elveflow64 = None

##########################
###The Global Variables###
##########################

logger = logging.getLogger(__name__)

#################
###The Classes###
#################

class PressureController:
    """
    def: This class connects to the OB1 pressure controller.
    """
    def __init__(self, config):
        if Elveflow64 is None:
            logger.error("Elveflow64 library not available.")
            raise RuntimeError("Elveflow64 library not available.")

        logger.info("Starting pressure controller communication...")

        self.config_path = os.path.join(config["Project Path"], "4_Config")  # Set the config path
        self.pressure_limit = config.get("Pressure Limit", None)

        self.Instr_ID = c_int32()

        try:
            self._initialize_device()
            self._load_calibration(config)
        except Exception as e:
            logger.error(f"Failed to initialize pressure controller: {e}")
            raise

        logger.info("Pressure controller communication successfully started")
        return

    def _initialize_device(self):
        """
        def: This funciton initializes the OB1 device and store the instrument ID.
        """
        error = OB1_Initialization('ASRL4::INSTR'.encode('ascii'), 5, 0, 0, 0, byref(self.Instr_ID))    #see User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            raise ConnectionError(f"ERROR: Unable to connect to OB1 device, error code: {error}")
        print(f"OB1 initialized with ID: {self.Instr_ID.value}")
        return

    def _load_calibration(self, config):
        """
        def: This function loads the calibration file path and initialize calibration array.
             The calibration_path is hardcoded in the script
        """
        self.config_path = os.path.join(config["Project Path"], "4_Config")              # Set the config path
        self.Calib = (c_double * 1000)()                                            # Calibration array with 1000 elements
        self.Calib_path = os.path.join(self.config_path, "Calib_latest.txt")             # Set the calibration path
        error = Elveflow_Calibration_Load(self.Calib_path.encode('ascii'), byref(self.Calib), 1000)     # Load the calibration
        if error != 0:
            print(f"WARNING: Calibration file could not be loaded, error code: {error}")

        return

    def calibrate(self):
        """
        def: This function performs calibration and save it to the calibration file.
        """
        print("Starting Calibration")
        self.Calib = (c_double * 1000)()
        self.Calib_path = os.path.join(self.config_path, "Calib_latest.txt")  # Set the calibration path
        OB1_Calib(self.Instr_ID.value, self.Calib, 1000)
        print("Calibration finished now its being stored")
        error = Elveflow_Calibration_Save(self.Calib_path.encode('ascii'), byref(self.Calib), 1000)     # This creates a new calib file, make sure to conduct the calibration properly
        print("Saving finished")
        if error == 0:
            print(f"Calibration successfully saved to {self.Calib_path}")
        else:
            print(f"ERROR: Calibration save failed, error code: {error}")
        return

    def set_pressure(self, p=0, ch=1):
        """
        def: This function sets the pressure at the pressure controller.
        :param p: Integer, which is the pressure value
        :return: ---
        """

        if p < 0 or p > self.pressure_limit:                                                               # Check if pressure is out of bounds
            raise ValueError("ERROR: PRESSURE OUT OF RANGE, choose within -1 to 6 bars.")

        set_channel = c_int32(int(1))                                                                # Convert channel (ch) to c_int32, this has to be done, as the pressure controller is programmed in C
        set_pressure = c_double(float(p))                                                       # Converto pressure to c_double
        print(set_pressure)
        print(self.Instr_ID)
        print(set_channel)
        error = OB1_Set_Press(self.Instr_ID.value, set_channel, set_pressure, byref(self.Calib), 1000)

        if error != 0:
            print(f"ERROR: Pressure could not be set, error code: {error}")
        return

    def get_pressure(self, ch=None):
        """
        def: This function reads the pressure of the controller
        """
        set_channel = c_int32(ch)                                        # Convert channel (ch) to c_int32, this has to be done, as the pressure controller is programmed in C
        get_pressure = c_double()                                       # Set pressure variable to a c_double
        error = OB1_Get_Press(self.Instr_ID.value, set_channel, 1, byref(self.Calib), byref(get_pressure), 1000)  # Acquire_data=1 -> read all the analog values
        if error != 0:
            print(f"ERROR: Unable to retrieve pressure, error code: {error}")
            return None
        return get_pressure.value