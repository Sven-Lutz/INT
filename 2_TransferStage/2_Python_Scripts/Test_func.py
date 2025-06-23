import random
import time


def connect_arduino():
    import serial.tools.list_ports
    from pyfirmata import Arduino
    import os
    import time
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        print(port)  # This will print all the available ports

    # Connecting to the board
    board = Arduino('COM3')
    print(board)
    board.digital[9].write(1) #venting valve open 1
    board.digital[10].write(0) #push 1 suck 0
    board.digital[12].write(0) #light Valve 1
    board.digital[13].write(0) #light Valve 2

def fill():
    time.sleep(0.5)
    print("fill")
    return {"Current Vessel Volume": round(random.uniform(800, 1000), 2),
            "Current Pressure": round(random.uniform(1.0, 2.0), 2),
            "Operation": "fill"}

def attachment():
    print("attachment")
    return {"Current Vessel Volume": round(random.uniform(500, 700), 2),
            "Current Pressure": round(random.uniform(0.5, 1.0), 2),
            "Operation": "Attachment"}

def empty():
    time.sleep(0.5)
    print("empty")
    return {"Current Vessel Volume": round(random.uniform(0, 100), 2),
            "Current Pressure": round(random.uniform(0.1, 0.5), 2),
            "Operation": "Empty"}

def add():
    print("add")
    return {"Current Vessel Volume": round(random.uniform(200, 300), 2),
            "Current Pressure": round(random.uniform(0.3, 0.7), 2),
            "Operation": "Add"}

def remove():
    print("remove")
    return {"Current Vessel Volume": round(random.uniform(100, 200), 2),
            "Current Pressure": round(random.uniform(0.2, 0.6), 2),
            "Operation": "Remove"}
def pause():
    print("Pausing Operation")


class Valve:
    """
    def: This class connects to valves via the arduino.
    """
    def __init__(self):
        from pyfirmata import Arduino
        print("Staring valve communication...")
        self.board = Arduino('COM3')                            # Connecting to the board, this is hardcoded
        self.valve ={"V1": [10,12],                             # Valve 1 is used for venting. It is set to pin 10 in the arduino and connected with the LED at pin 12. NO-Valve
                     "V2": [11,13],                             # Valve 2 is used for switching between the water and waste bottles. It is set to pin 11 in the arduino and connected with the LED at pin 13
                     "V3": [9,8],                               # Valve 3 is used for blocking the set_flow line. It is set to pin 9 in the arduino and connected with the LED at pin 8. NC-Valve
                     }
        self.vent_pos()                                         # Set valves into the safe position
        print("Valve communication successfully started\n")
        return

    def _switch_v(self, v, state):
        """
        def: This function switches the state of the valve
        :param v: String which indicates the name of the valve.
        :param state: State of the valve, it can be open or closed.
        :return: ---
        """
        print(f"{v}: {state}")
        self.board.digital[self.valve[v][0]].write(state)       # Changes the state of the valve 1 or 2.
        self.board.digital[self.valve[v][1]].write(state)       # Changes the state of the LED for visual feedback

        return

    def vent_pos(self):
        """
        def: This function opens the venting valve.
             This state is considered as safe since the bottles are not under pressure.
        """
        self._switch_v("V1", 0)                         # Open venting valve
        self._switch_v("V3", 0)                         # Closing blocking valve
        return

    def suck_pos(self):
        """
        def: This function changes the valves to the sucking state,
             meaning that the waste water bottle is filled.
        """
        self._switch_v("V1", 1)                         # Close venting valve
        self._switch_v("V2", 0)                         # Switch to waste bottle
        self._switch_v("V3", 1)                         # Open blocking valve
        return

    def push_pos(self):
        """
        def: This function changes the valves to the sucking state,
             meaning that the waste water bottle is filled.
        """
        self._switch_v("V1", 1)                         # Close venting valve
        self._switch_v("V2", 1)                         # Switch to water bottle
        self._switch_v("V3", 1)                         # Open blocking valve
        return

    def block_pos(self):
        """
        def: This function closes the blocking valve
        """
        self._switch_v("V3",0)
        return

    def open_pos(self):
        """
        def. This function opens the blocking valve
        """
        self._switch_v("V3", 1)
        return


class Kill:
    def __init__(self):
        print("Initialisieren")

    def test(self):
        print("Does something")

    def __del__(self):
        print("Destroy")


def main():
    print(random.randint(0,10))

if __name__ == "__main__":
    main()



