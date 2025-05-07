###################
###The Libraries###
###################

import os
import Configurator
import Experiment

import tkinter as tk

##########################
###The Global Variables###
##########################

project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#################
###The Classes###
#################

class MainApplication(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("GUI Layout with Frames and Titles")

        self.project_frame = None
        self.main_frame = None
        self.parameter_frame =None
        self.state_variable_frame = None

        self.current_thread = None
        self.current_function = None

        self.project = project
        self.writer = Configurator.WritingManager(project)

        self.config, _ = self.writer.read_yaml("both")
        self.yaml_file = os.path.join(self.config["Project Path"],"4_Config","temp.yaml")      # For debugging reasons the file is called temp_test


        return

if __name__ == "__main__":
    app = MainApplication()
    app.mainloop()