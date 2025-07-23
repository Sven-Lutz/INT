import time
import logging

from pyfirmata import Arduino

logger = logging.getLogger(__name__)


class Valve:
    """
    def: Class to control valves connected via an Arduino. Configuration is loaded through ConfigManager from valve.yaml.
    """

    def __init__(self, config:dict ):
        logger.info("Staring valve communication")
        port = config.get("COM Port",None)
        self.valves = config.get("Valves", {})

        if not self.valves:
            raise ValueError("Valve configuration is empty or missing 'valves' key.")

        #self.board = Arduino(port)                                      # Connecting to the board
        #time.sleep(1.0)                                                 # allow Arduino to initialize

        self.state = {}                                                 # Track current valve states

        self.vent_pos()                                                 # Set valves into the safe position
        logger.info("Valve communication successfully started")
        return

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return

    def shutdown(self):
        logger.debug("Shutting down valve system")
        self.vent_pos()
        #self.board.exit()
        return

    def _switch_valve(self, name, state):
        """
        def: Switches the given valve (and its LED) to the specified state.
        :param name: str - valve identifier (e.g., "Venting")
        :param state: int - 1 (open/on), 0 (closed/off)
        :return: ---
        """
        if name not in self.valves:
            logger.error(f"Valve '{name}' is not defined in the configuration.")
            raise ValueError(f"Valve '{name}' is not defined in the configuration.")

        pin_valve, pin_led = self.valves[name]
        #self.board.digital[pin_valve].write(state)
        #self.board.digital[pin_led].write(state)

        self.state[name] = state
        logger.info(f"{name}: {'OPEN' if state else 'CLOSED'} | Valve states: {self.state}")
        return

    def vent_pos(self):
        """Set to safe default: vent open, container closed."""
        self._switch_valve("Venting", 0)                        # Open venting valve
        self._switch_valve("Container", 0)                      # Closing container valve
        return

    def suck_pos(self):
        """Waste collection: vent closed, waste selected, open flow."""
        self._switch_valve("Venting", 1)                        # Close venting valve
        self._switch_valve("Liquid", 0)                         # Switch to waste bottle
        self._switch_valve("Container", 1)                      # Open container valve
        return

    def push_pos(self):
        """Water push: vent closed, water selected, open flow."""
        self._switch_valve("Venting", 1)                        # Close venting valve
        self._switch_valve("Liquid", 1)                         # Switch to water bottle
        self._switch_valve("Container", 1)                      # Open container valve
        return

    def block_pos(self):
        """Block flow by closing container valve."""
        self._switch_valve("Container", 0)
        return

    def open_pos(self):
        """Open container valve for flow."""
        self._switch_valve("Container", 1)
        return
