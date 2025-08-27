import os
import logging

from hardware.drivers.Elveflow64 import *

logger = logging.getLogger(__name__)

class FlowSensor:
    """
    def: This class connects to the BFS flow controller.
    """
    def __init__(self, config: dict):
        logger.info("Staring set_flow controller communication...")
        self.config = config
        self.Instr_ID = c_int32()
        self._initialize_device()
        logger.info("Flow controller communication successfully started")

        return

    def _initialize_device(self):
        """
        def: This function initializes the BFS set_flow controller and retrieves liquid density for calibration.
        """
        error = BFS_Initialization(self.config.get("COM Port").encode('ascii'), byref(self.Instr_ID))            # See User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            logger.error(f"ERROR: Unable to establish connection, error code: {error}")
            raise ConnectionError(f"ERROR: Unable to establish connection, error code: {error}")
        logger.info(f"BFS2 initialized with ID: {self.Instr_ID.value}")

        self._retrieve_density()                                                    # Get the density which has to be done in the beginning
        return

    def _retrieve_density(self):
        """
        def: This function retrieves and prints the liquid density for calibration purposes.
        """
        density = c_double(-1)
        error = BFS_Get_Density(self.Instr_ID.value, byref(density))  # Get density
        if error == 0:
            logger.info(f"Density retrieved: {round(density.value, 3)} kg/m^3")
        else:
            logger.warning(f"WARNING: Unable to retrieve density, error code: {error}")
        return

    def shutdown(self):
        logger.info("Shutting down Flow Sensor")

        try:
            # Call the ElveFlow destructor to release the device
            error = BFS_Destructor(self.Instr_ID.value)
            if error != 0:
                logger.warning(f"BFS_Destructor returned error code: {error}")
            else:
                logger.info("Flow sensor communication successfully closed.")
        except Exception as e:
            logger.error(f"Exception during FlowSensor shutdown: {e}")
        return

    def get_flow(self):
        """
        def: This function read the set_flow of the sensor.
        :return: float which is the flow.value
        """
        limit = self.config.get("Flow Limit")
        flow = c_double(-1)                                                         # Convert the set_flow to c_double
        error = BFS_Get_Flow(self.Instr_ID.value, byref(flow))                      # Read the set_flow
        if error != 0:
            logger.error(f"ERROR: Unable to read set_flow, error code: {error}")
            return None
        if flow.value >= self.config.get("Flow Limit"):
            logger.warning(f"Flow is exceeding calibrated range of sensor {self.config.get("Flow Limit")/1000}ml/min")
        return flow.value