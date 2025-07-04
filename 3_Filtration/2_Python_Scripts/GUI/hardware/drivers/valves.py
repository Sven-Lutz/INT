import logging
import serial



logger = logging.getLogger(__name__)


class ValveController:
    """
    def: This class connects to valves via the rly02.
    """
    def __init__(self, config):
        serial_path = config["COM Port"]
        self.relais = RelayController(serial_path)
        logger.info("ValveController initialized.")

        return

    def filtration(self):
        logger.debug("Setting valves to filtration mode.")
        self.relais.turn_relay_1_on()
        self.relais.turn_relay_2_off()
        return

    def filling_solution(self):
        logger.debug("Setting valves to filling mode.")
        self.relais.turn_relay_1_off()
        self.relais.turn_relay_2_on()
        return

    def venting(self):
        logger.debug("Setting valves to venting mode.")
        self.relais.turn_relay_1_off()
        self.relais.turn_relay_2_on()
        return

    def all_shut(self):
        logger.debug("Turning all valves off.")
        self.relais.turn_relay_1_on()
        self.relais.turn_relay_2_on()
        return

    def all_open(self):
        logger.debug("Turning all valves on.")
        self.relais.turn_relay_1_off()
        self.relais.turn_relay_2_off()
        return

    def disconnect(self):
        logger.info("Closing ValveController: turning valves to venting mode.")
        self.venting()


class RelayController:
    def __init__(self, serial_path="COM6", baud_rate=9600):
        self.serial_path = serial_path
        self.baud_rate = baud_rate
        self.commands = {
            'relay_1_on': 0x65,
            'relay_1_off': 0x6F,
            'relay_2_on': 0x66,
            'relay_2_off': 0x70,
            'info': 0x5A,
            'relay_states': 0x5B,
        }

    def send_command(self, cmd, read_response=False):
        ser = serial.Serial(self.serial_path, self.baud_rate)
        ser.write(chr(cmd).encode())
        response = ser.read() if read_response else None
        ser.close()
        return response

    def turn_relay_1_on(self):
        self.send_command(self.commands['relay_1_on'])
        return

    def turn_relay_1_off(self):
        self.send_command(self.commands['relay_1_off'])
        return

    def turn_relay_2_on(self):
        self.send_command(self.commands['relay_2_on'])
        return

    def turn_relay_2_off(self):
        self.send_command(self.commands['relay_2_off'])
        return

def main():
    valve_ctrl = ValveController()
    #valve_ctrl.venting()
    valve_ctrl.filling_solution()# or any method you want to test

if __name__ == "__main__":
    main()