###################
###The Libraries###
###################

import Configurator
import time
import os
import random

import matplotlib.pyplot as plt
import pandas as pd

from simple_pid import PID

#################
###The Classes###
#################

class Experimentator:
    """
    def: This class manages the experiment protocol.
    """
    def __init__(self, writer):
        self.writer = writer

        self.config, _ = self.writer.read_yaml("both")
        self.temp, _ = self.writer.read_yaml("temp")                            # Read temp.yaml, since some variable have to be initialized from the beginning


        self.valve = Configurator.Valve(self)
        self.OB1 = Configurator.PressureController(self.config)
        self.BFS = Configurator.FlowSensor()


        self.init_vol = None
        self.set_flow = None

        self.max_vol = self.config["Maximum Volume"]
        self.p_term = self.config["P Term"]
        self.i_term = self.config["I Term"]
        self.d_term = self.config["D Term"]

        return

    def setup_experiment(self):
        """
        def: This function sets some initial parameters. It is called every time an operation is performed,
             since each operation has different initial values.
        """
        #self.temp, _ = self.writer.read_yaml("temp")                            # Read temp.yaml
        self.init_vol = self.temp["Current Vessel Volume"]                      # Get the initial volume
        self.set_flow = self.temp["Set Flow"]                                   # Get the set flow
        print(f"Current volume in vessel: {round(self.init_vol, 3)} uL")
        return