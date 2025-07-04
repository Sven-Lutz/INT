class FlowSensor:
    """
    def: This class connects to the BFS flow controller.
    """
    def __init__(self):
        print("Staring set_flow controller communication...")
        self.Instr_ID = c_int32()
        self._initialize_device()
        print("Flow controller communication successfully started")
        print("")
        return

    def _initialize_device(self):
        """
        def: This function initializes the BFS set_flow controller and retrieves liquid density for calibration.
        """
        error = BFS_Initialization("COM5".encode('ascii'), byref(self.Instr_ID))            # See User Guide to determine regulator types and NIMAX to determine the instrument name
        if error != 0:
            raise ConnectionError(f"ERROR: Unable to establish connection, error code: {error}")
        print(f"BFS2 initialized with ID: {self.Instr_ID.value}")

        self._retrieve_density()                                                    # Get the density which has to be done in the beginning
        return

    def _retrieve_density(self):
        """
        def: This function retrieves and prints the liquid density for calibration purposes.
        """
        density = c_double(-1)
        error = BFS_Get_Density(self.Instr_ID.value, byref(density))                # Get density
        if error == 0:
            print(f"Density retrieved: {round(density.value,3)} kg/m^3")
        else:
            print(f"WARNING: Unable to retrieve density, error code: {error}")
        return