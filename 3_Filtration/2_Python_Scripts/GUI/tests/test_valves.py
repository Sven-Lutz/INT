from ..hardware.drivers.valves import ValveController

def main():
    valve_ctrl = ValveController()
    valve_ctrl.all_off()  # or any method you want to test

if __name__ == "__main__":
    main()
