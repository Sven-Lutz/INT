import logging

logger = logging.getLogger(__name__)


class FlowSensor:
    """Dummy BFS flow sensor for simulation/offline use."""

    def __init__(self):
        logger.debug("Starting dummy flow sensor communication...")
        self.Instr_ID = c_int32()
        self._initialize_device()
        logger.debug("Dummy flow sensor communication started.")

    def _initialize_device(self):
        error = BFS_Initialization("COM5".encode("ascii"), byref(self.Instr_ID))
        if error != 0:
            raise ConnectionError(f"Unable to establish connection, error code: {error}")
        logger.debug("BFS2 initialized with ID: %s", self.Instr_ID.value)
        self._retrieve_density()

    def _retrieve_density(self):
        density = c_double(-1)
        error = BFS_Get_Density(self.Instr_ID.value, byref(density))
        if error == 0:
            logger.debug("Density retrieved: %.3f kg/m^3", density.value)
        else:
            logger.warning("Unable to retrieve density, error code: %s", error)