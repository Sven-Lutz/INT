import os
import logging
import random

#from hardware.drivers.Elveflow64 import *

logger = logging.getLogger(__name__)

class PressureController:
    """
    def: This class connects to the OB1 pressure controller.
    """
    def __init__(self, config: dict):
        logger.info("Starting pressure controller communication...")
        self.pressure = None
        self.channel = None

        self._initialize_device()
        self._load_calibration()
        logger.info("Pressure controller  communication successfully started")
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
        def: This function initializes the OB1 device and store the instrument ID.
        """
        logger.info(f"Dummy OB1 initialized with ID")
        return

    def _load_calibration(self):
        """
        def: This function loads the calibration file path and initialize calibration array.
             The calibration_path is hardcoded in the script
        """
        self.set_pressure(0)                                                        # Set initial pressure to zero
        return

    def calibrate(self):
        """
        def: This function performs calibration and save it to the calibration file.
        """
        logger.info(f"Calibration successfully saved")
        return

    def set_pressure(self, p):
        """
        def: This function sets the pressure at the pressure controller.
        :param p: Integer, which is the pressure value
        :return: ---
        """
        self.channel = 1                                                                # Convert channel (1) to c_int32, this has to be done, as the pressure controller is programmed in C
        self.pressure = p
        logger.debug(f"Pressure {self.pressure} at channel {self.channel}")
        return

    def get_pressure(self):
        """
        def: This function reads the pressure of the controller
        """
        #noise = random.gauss(mu = 0, sigma = self.pressure * 0.01)
        logger.debug(f"Pressure: {self.pressure}")
        #pressure = self.pressure + noise
        return self.pressure