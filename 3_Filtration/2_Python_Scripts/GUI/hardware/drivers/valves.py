import logging
import rly02

logger = logging.getLogger(__name__)

class ValveController:
    """
    def: This class connects to valves via the rly02.
    """
    def __init__(self):
        logger.info("ValveController initialized.")
        return

    def filtration(self):
        logger.debug("Setting valves to filtration mode.")
        rly02.turn_relay_1_off()
        rly02.turn_relay_2_on()
        return

    def filling(self):
        logger.debug("Setting valves to filling mode.")
        rly02.turn_relay_1_on()
        rly02.turn_relay_2_off()
        return

    def venting(self):
        logger.debug("Setting valves to venting mode.")
        rly02.turn_relay_1_on()
        rly02.turn_relay_2_off()
        return

    def all_off(self):
        logger.debug("Turning all valves off.")
        rly02.turn_relay_1_off()
        rly02.turn_relay_2_off()
        return

    def all_on(self):
        logger.debug("Turning all valves on.")
        rly02.turn_relay_1_on()
        rly02.turn_relay_2_on()
        return

    def close(self):
        logger.info("Closing ValveController: turning valves to venting mode.")
        self.venting()

def main():
    valve_ctrl = ValveController()
    #valve_ctrl.venting()
    valve_ctrl.filling()# or any method you want to test

if __name__ == "__main__":
    main()