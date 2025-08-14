import logging


logger = logging.getLogger(__name__)

class ContainerSelector:
    def __init__(self, config):
        logger.info("Starting container selector communication...")
        self.config = config
        self._initialize_device()

        logger.info("Transfer container selector communication successfully started")
        return

    def _initialize_device(self):
        """
        def: This function initializes the OB1 device and store the instrument ID.
        """
        logger.info(f"MUX initialized")
        return

    def _confirm_channel(self, channel):
        mux_valves = set()
        for container in self.config.get("Containers", {}).values():
            for key in container:
                if key == "MUX Valve":
                    mux_valves.add(container[key])
        return channel in mux_valves

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
        logger.debug(f"MUX valve selected: {mux_valve}, type: {type(mux_valve)}")
        if mux_valve is None:
            logger.warning(f"MUX valve not defined for container '{matched_key}'")
            raise ValueError(f"ERROR: MUX valve not defined for container '{matched_key}'")

        if self._confirm_channel(mux_valve):
            logger.debug(f"MUX Valve set to {mux_valve} for container '{matched_key}'")
        else:
            logger.warning("Channel is not connected in System")
            raise ValueError("ERROR: Channel is not connected in System")
        return
