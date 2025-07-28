from hardware.drivers.rly02.rly02 import RLY02

class VacuumPump:
    def __init__(self, config:dict):
        self.relays = RLY02(port=config.get("COM Port"))
        return

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._shut_down()
        return

    def start(self):
        self.relays.turn_on()
        return

    def stop(self):
        self.relays.turn_off()
        return

    def _shut_down(self):
        self.stop()
        return
