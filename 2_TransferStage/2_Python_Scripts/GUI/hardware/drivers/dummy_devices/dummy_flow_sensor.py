import os
import logging
import random


logger = logging.getLogger(__name__)

class FlowSensor:
    """
    def: This class connects to the BFS flow controller.
    """
    def __init__(self, pressure_controller):
        logger.info("Staring set_flow controller communication...")
        self.config = {}
        self.pressure_ctrl = pressure_controller
        self._initialize_device()
        logger.info("Flow controller communication successfully started")
        self.k = 7
        return

    def _initialize_device(self):
        """
        def: This function initializes the BFS set_flow controller and retrieves liquid density for calibration.
        """
        logger.info(f"Dummy BFS2 initialized")
        self._retrieve_density()                                                    # Get the density which has to be done in the beginning
        return

    def _retrieve_density(self):
        """
        def: This function retrieves and prints the liquid density for calibration purposes.
        """
        logger.info(f"Density retrieved: {1000} kg/m^3")
        return

    def shutdown(self):
        logger.info("Shutting down Flow Sensor")
        return

    def get_flow(self):
        """
        def: This function read the set_flow of the sensor.
        :return: float which is the flow.value
        """
        limit = self.config.get("Flow Limit")
        pressure = self.pressure_ctrl.pressure
        noise = random.gauss(0,0.02 * self.k * pressure)

        flow = self.k * pressure + noise
        return flow