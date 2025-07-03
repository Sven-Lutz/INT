###################
###The Libraries###
###################

import os
import logging

from ctypes import c_int32, c_double, byref

try:
    from hardware.drivers.Elveflow64 import (
        OB1_Initialization,
        OB1_Set_Press,
        OB1_Get_Press,
        OB1_Calib,
        Elveflow_Calibration_Load,
        Elveflow_Calibration_Save
    )
except ImportError:
    OB1_Initialization = OB1_Set_Press = OB1_Get_Press = OB1_Calib = None
    Elveflow_Calibration_Load = Elveflow_Calibration_Save = None

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
        if OB1_Initialization is None:
            logger.error("Elveflow64 library not available.")
            raise RuntimeError("Elveflow64 library not available.")

        logger.info("Starting pressure controller communication...")

        self.config_path = os.path.join(config["Project Path"], "4_Config")  # Set the config path
        self.Calib_path = os.path.join(self.config_path, "OB1_Calib_latest.txt")
        self.pressure_limit = config.get("Pressure Limit", None)
        if self.pressure_limit is None:
            logger.error("Pressure Limit not found")
            raise LookupError("Pressure Limit not Found")

        self.Calib = (c_double * 1000)()
        self.Instr_ID = c_int32()

        try:
            self._initialize_device()
            self._load_calibration()
        except Exception as e:
            logger.error(f"Failed to initialize pressure controller: {e}")
            raise

        logger.info("Pressure controller communication successfully started")
        return

    def _initialize_device(self):
        """
        def: This function initializes the OB1 device and store the instrument ID.
        """
        logger.debug("Calling OB1_Initialization...")
        error = OB1_Initialization('ASRL4::INSTR'.encode('ascii'), 5, 0, 0, 0, byref(self.Instr_ID))    #see User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            logger.error(f"Error:Unable to connect to OB1 device. Error code: {error}")
            raise ConnectionError(f"ERROR: Unable to connect to OB1 device, error code: {error}")
        logger.debug(f"OB1 initialized with ID: {self.Instr_ID.value}")
        return

    def _load_calibration(self):
        """
        def: This function loads the calibration file path and initialize calibration array.
             The calibration_path is hardcoded in the script.
        """
        logger.debug(f"Loading calibration from {self.Calib_path}")
        error = Elveflow_Calibration_Load(self.Calib_path.encode('ascii'), byref(self.Calib), 1000)
        if error != 0:
            logger.warning(f"Calibration file could not be loaded. Error code: {error}")
        return

    def calibrate(self):
        """
        def: This function performs calibration and save it to the calibration file.
        """
        logger.info("Starting OB1 calibration...")
        OB1_Calib(self.Instr_ID.value, self.Calib, 1000)

        logger.info("Calibration completed. Saving to file...")
        error = Elveflow_Calibration_Save(self.Calib_path.encode('ascii'), byref(self.Calib), 1000)     # This creates a new calib file, make sure to conduct the calibration properly
        print("Saving finished")
        if error == 0:
            logger.info(f"Calibration saved to {self.Calib_path}")
        else:
            logger.error(f"Failed to save calibration. Error code: {error}")
        return

    def set_pressure(self, pressure: float = 0, channel: int = 1):
        """
        def: This function sets the pressure on a given channel at the pressure controller.
        :param pressure: Float, which is the pressure value
        :param channel: Integer, which is the channel number
        :return: ---
        """

        if pressure < 0 or pressure > self.pressure_limit:                                                               # Check if pressure is out of bounds
            logger.error("Error: pressure out of range")
            raise ValueError(f"ERROR: PRESSURE OUT OF RANGE, choose within 0 to {self.pressure_limit} bars.")

        set_channel = c_int32(channel)                                                                # Convert channel (ch) to c_int32, this has to be done, as the pressure controller is programmed in C
        set_pressure = c_double(pressure)                                                       # Converto pressure to c_double

        logger.debug(f"Setting pressure: {pressure} on channel {channel}")

        error = OB1_Set_Press(self.Instr_ID.value, set_channel, set_pressure, byref(self.Calib), 1000)

        if error != 0:
            logger.error(f"Failed to set pressure. Error code: {error}")
            raise IOError(f"ERROR: Pressure could not be set, error code: {error}")
        return

    def get_pressure(self, channel: int = 1) -> float | None:
        """
        def: This function reads the pressure of the controller
        :param channel: Integer which is the channel number
        :return: float if successful, none if error
        """
        set_channel = c_int32(channel)                                        # Convert channel (ch) to c_int32, this has to be done, as the pressure controller is programmed in C
        get_pressure = c_double()                                       # Set pressure variable to a c_double
        error = OB1_Get_Press(self.Instr_ID.value, set_channel, 1, byref(self.Calib), byref(get_pressure), 1000)  # Acquire_data=1 -> read all the analog values
        if error != 0:
            logger.error(f"Failed to retrieve pressure. Error code: {error}")
            return None
        logger.debug(f"Read pressure: {get_pressure.value} from channel {channel}")
        return get_pressure.value

    def close(self):
        """
        Placeholder for cleanup logic if needed.
        """
        logger.info("Closing pressure controller (not implemented).")
        return