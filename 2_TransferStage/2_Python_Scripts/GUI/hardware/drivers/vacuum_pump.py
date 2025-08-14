from hardware.drivers.rly02.rly02 import RLY02

class VacuumPump:
    def __init__(self, config:dict):
        self.relays = RLY02(port=config.get("COM Port"))
        return

    def start(self):
        self.relays.turn_on()
        return

    def stop(self):
        self.relays.turn_off()
        return

    def shutdown(self):
        self.stop()
        return
