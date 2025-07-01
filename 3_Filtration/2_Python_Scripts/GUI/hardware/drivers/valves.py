import rly02

class ValveController:
    """
    def: This class connects to valves via the rly02.
    """
    def __init__(self):
        return

    def filtration(self):
        rly02.turn_relay_1_off()
        rly02.turn_relay_2_on()
        return

    def filling(self):
        rly02.turn_relay_1_on()
        rly02.turn_relay_2_off()
        return

    def venting(self):
        rly02.turn_relay_1_on()
        rly02.turn_relay_2_off()
        return

    def all_off(self):
        rly02.turn_relay_1_off()
        rly02.turn_relay_2_off()
        return

    def all_on(self):
        rly02.turn_relay_1_on()
        rly02.turn_relay_2_on()
        return