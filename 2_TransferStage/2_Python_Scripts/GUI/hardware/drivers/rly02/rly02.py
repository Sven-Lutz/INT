import serial
import time
from struct import unpack

class RLY02:
    def __init__(self, port='COM11', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.commands = {
            'relay_1_on': 0x65,
            'relay_1_off': 0x6F,
            'relay_2_on': 0x66,
            'relay_2_off': 0x70,
            'info': 0x5A,
            'relay_states': 0x5B,
        }

    def _send_command(self, cmd, read_response=False):
        with serial.Serial(self.port, self.baudrate) as ser:
            ser.write(chr(cmd).encode())
            return ser.read() if read_response else None

    def relay_1_on(self):
        self._send_command(self.commands['relay_1_on'])

    def relay_1_off(self):
        self._send_command(self.commands['relay_1_off'])

    def click_relay_1(self):
        self.relay_1_on()
        time.sleep(1)
        self.relay_1_off()

    def relay_2_on(self):
        self._send_command(self.commands['relay_2_on'])

    def relay_2_off(self):
        self._send_command(self.commands['relay_2_off'])

    def click_relay_2(self):
        self.relay_2_on()
        time.sleep(1)
        self.relay_2_off()

    def turn_on(self):
        self.relay_1_on()
        self.relay_2_on()

    def turn_off(self):
        self.relay_1_off()
        self.relay_2_off()

    def get_relay_states(self):
        raw = self._send_command(self.commands['relay_states'], read_response=True)
        response = unpack('b', raw)[0]
        states = {
            0: {'1': False, '2': False},
            1: {'1': True, '2': False},
            2: {'1': False, '2': True},
            3: {'1': True, '2': True},
        }
        return states.get(response, {'1': None, '2': None})
