import logging

from hardware.drivers.Elveflow64 import *

logger = logging.getLogger(__name__)

class ContainerSelector:
    def __init__(self, config):
        logger.info("Starting container selector communication...")
        self.config = config
        self.Instr_ID = c_int32()
        self._initialize_device()

        logger.info("Transfer container selector communication successfully started\n")
        return

    def _initialize_device(self):
        """
        def: This funciton initializes the OB1 device and store the instrument ID.
        """
        error = MUX_DRI_Initialization(self.config.get("COM Port").encode('ascii'), byref(self.Instr_ID))    #see User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            logger.error(f"Unable to connect to MUX device, error code: {error}")
            raise ConnectionError(f"ERROR: Unable to connect to MUX device, error code: {error}")
        logger.info(f"MUX initialized with ID: {self.Instr_ID.value}")
        return

    def _confirm_channel(self, channel):
        mux_valves = set()
        for container in self.config.get("Containers", {}).values():
            for key in container:
                if key == "MUX Valve":
                    mux_valves.add(container[key])
        return channel in mux_valves

    def get_container(self):
        valve = c_int32(-1)
        MUX_DRI_Get_Valve(self.Instr_ID.value, byref(valve))  # get the active valve. it returns 0 if valve is busy.
        logger.debug('selected channel', valve.value)
        return valve.value

    def select_container(self, container_name: str):
        # Make sure the container name matches exactly (e.g., "5 Sample", not "5Sample")
        containers = self.config.get("Containers", {})

        # Find the container key that matches the input name (case-insensitive and ignoring whitespace if needed)
        matched_key = next((key for key in containers if key.replace(" ", "").lower() == container_name.replace(" ", "").lower()), None)

        if not matched_key:
            logger.warning(f"Container '{container_name}' not found in configuration.")
            raise ValueError(f"ERROR: Container '{container_name}' not found in configuration.")

        container_info = containers[matched_key]

        # Handle both "MUX Valve" and "MUX valve" keys
        mux_valve = int(container_info.get("MUX Valve"))
        logger.info(f"MUX valve selected: {mux_valve}, type: {type(mux_valve)}")
        if mux_valve is None:
            logger.warning(f"MUX valve not defined for container '{matched_key}'")
            raise ValueError(f"ERROR: MUX valve not defined for container '{matched_key}'")

        if self._confirm_channel(mux_valve):
            error = MUX_DRI_Set_Valve(self.Instr_ID.value, mux_valve, 0)
            if error != 0:
                logger.error(f"Unable to select Channel: {error}")
                raise ConnectionError(f"ERROR: Unable to select Channel {mux_valve}: {error}")
            logger.debug(f"MUX Valve set to {mux_valve} for container '{matched_key}'")
        else:
            logger.warning("Channel is not connected in System")
            raise ValueError("ERROR: Channel is not connected in System")

        return
