import os
import logging

from hardware.drivers.Elveflow64 import *

logger = logging.getLogger(__name__)

class PressureController:
    """
    def: This class connects to the OB1 pressure controller.
    """
    def __init__(self, config: dict):
        logger.info("Starting pressure controller communication...")
        self.config = config
        self.Instr_ID = c_int32()
        self._initialize_device()
        self._load_calibration()
        logger.info("Pressure controller  communication successfully started\n")
        return

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return

    def shutdown(self):
        logger.info("Shutting down Pressure Controller")
        self.set_pressure(0)
        return

    def _initialize_device(self):
        """
        def: This funciton initializes the OB1 device and store the instrument ID.
        """
        error = OB1_Initialization(self.config.get("COM Port").encode('ascii'), 5, 0, 0, 0, byref(self.Instr_ID))    #see User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            logger.error(f"ERROR: Unable to connect to OB1 device, error code: {error}")
            raise ConnectionError(f"ERROR: Unable to connect to OB1 device, error code: {error}")
        logger.info(f"OB1 initialized with ID: {self.Instr_ID.value}")
        return

    def _load_calibration(self):
        """
        def: This function loads the calibration file path and initialize calibration array.
             The calibration_path is hardcoded in the script
        """
        config_path = self.config.get("Config Path")              # Set the config path
        self.Calib = (c_double * 1000)()                                            # Calibration array with 1000 elements
        self.Calib_path = os.path.join(config_path, "Calib_latest.txt")             # Set the calibration path

        error = Elveflow_Calibration_Load(self.Calib_path.encode('ascii'), byref(self.Calib), 1000)     # Load the calibration
        if error != 0:
            logger.warning(f"WARNING: Calibration file could not be loaded, error code: {error}")

        self.set_pressure(0)                                                        # Set initial pressure to zero
        return

    def calibrate(self):
        """
        def: This function performs calibration and save it to the calibration file.
        """
        OB1_Calib(self.Instr_ID.value, self.Calib, 1000)
        error = Elveflow_Calibration_Save(self.Calib_path.encode('ascii'), byref(self.Calib), 1000)     # This creates a new calib file, make sure to conduct the calibration properly
        if error == 0:
            logger.info(f"Calibration successfully saved to {self.Calib_path}")
        else:
            logger.error(f"ERROR: Calibration save failed, error code: {error}")
        return

    def set_pressure(self, p=0):
        """
        def: This function sets the pressure at the pressure controller.
        :param p: Integer, which is the pressure value
        :return: ---
        """
        limits = self.config.get("Pressure Limits")
        if p < limits[0] or p > limits[1]:                                                               # Check if pressure is out of bounds
            logger.error(f"ERROR: PRESSURE OUT OF RANGE, choose within {limits[0]} to {limits[1]} mbar.")
            raise ValueError(f"ERROR: PRESSURE OUT OF RANGE, choose within {limits[0]} to {limits[1]} mbar.")

        set_channel = c_int32(1)                                                                # Convert channel (1) to c_int32, this has to be done, as the pressure controller is programmed in C
        set_pressure = c_double(float(p))                                                       # Converto pressure to c_double
        error = OB1_Set_Press(self.Instr_ID.value, set_channel, set_pressure, byref(self.Calib), 1000)

        if error != 0:
            logger.error(f"ERROR: Pressure could not be set, error code: {error}")
        return

    def get_pressure(self):
        """
        def: This function reads the pressure of the controller
        """
        set_channel = c_int32(1)                                        # Convert channel (1) to c_int32, this has to be done, as the pressure controller is programmed in C
        get_pressure = c_double()                                       # Set pressure variable to a c_double
        error = OB1_Get_Press(self.Instr_ID.value, set_channel, 1, byref(self.Calib), byref(get_pressure), 1000)  # Acquire_data=1 -> read all the analog values
        if error != 0:
            logger.error(f"ERROR: Unable to retrieve pressure, error code: {error}")
            return None
        return get_pressure.value