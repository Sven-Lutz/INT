###################
###The Libraries###
###################

import threading
import time
import datetime
import yaml
import os

from PIL.ImageOps import expand

import Configurator
import Experiment
import Test_func

import tkinter as tk

from tkinter import ttk
from functools import partial
from tkinter import messagebox
from state import pause_event, stop_event, measurement_event  # Import the shared pause_event from state.py

##########################
###The Global Variables###
##########################

project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#################
###The Classes###
#################


class ProjectFrame(tk.Frame):
    """
    def: This class gives information about the project path.
    """
    def __init__(self, root):
        super().__init__(root)
        self.configure(borderwidth=2, relief="groove", bg="lightblue")                                      # Set frame color

        self.project_label = tk.Label(self, text="Project:", bg="lightblue")                                # Set label text
        self.project_label.pack(side=tk.LEFT, padx=5)

        self.project_var = tk.StringVar()                                                                   # StringVar to hold the text
        self.project_var.set(project)                                                                       # Set initial text from the global variable

        self.project_entry = tk.Entry(self, textvariable=self.project_var, state='readonly', width=60)      # Project Label and Entry (Uneditable)
        self.project_entry.pack(side=tk.LEFT, padx=5)
        return

class ParameterFrame(tk.LabelFrame):
    """
    def: This function is able so set the parameter used in the experiment and to trigger the experiment, it is placed on the main frame.
    """
    def __init__(self, root, state_variable_frame, config, writer, experiment, start_callback, automatic_callback):
        super().__init__(root, text="Parameters", borderwidth=2, relief="groove", bg="lightgreen")          # Set frame color and title
        
        self.start_callback = start_callback
        self.automatic_callback = automatic_callback
        self.config = config
        self.writer = writer
        self.experiment = experiment
        self.state_variable_frame = state_variable_frame
        self.main_frame = root

        self.dropdown_menu = None
        self.dropdown_var = None

        self.entry_frame = None
        self.entries = None
        self.entry_states = {}
        self.active_entry = None

        self.button_frame = None
        self.buttons = None
        self.button_func = None

        self.add_dropdown()
        self.add_entries()
        self.add_buttons()
        return

    @property
    def temp(self):
        return self.experiment.temp                                 # Get the 'temp' dictionary from the experiment instance

    @temp.setter
    def temp(self, value):
        if isinstance(value, dict):                                 # If 'value' is a dictionary, update experiment.temp
            self.experiment.temp.update(value)                      # Update existing dictionary with new values
        else:
            raise ValueError("temp must be a dictionary or dictionary-like object")

    def add_dropdown(self):
        """
        def: This function adds teh dropdown for the different containers in the Parameter Frame
        :return: ---
        """
        self.dropdown_frame = tk.Frame(self, bg="lightblue")
        self.dropdown_frame.pack(fill=tk.X)  # X direction to keep above entries

        tk.Label(self.dropdown_frame, text="Select Mode:", bg="lightblue").pack(side=tk.LEFT, padx=5, pady=5)

        self.dropdown_var = tk.StringVar()
        self.dropdown_var.set(self.temp["Selected Container"])  # Initial dropdown value

        options = self.config["Containers"].keys()  # Replace with actual modes if needed
        dropdown_menu = tk.OptionMenu(self.dropdown_frame, self.dropdown_var, *options)
        dropdown_menu.config(width=20)
        dropdown_menu.pack(side=tk.LEFT, padx=5, pady=5)

        # Optionally bind an action on change:
        self.dropdown_var.trace_add("write", self.on_dropdown_change)

    def on_dropdown_change(self, *args):
        selected = self.dropdown_var.get()
        self.writer.update_yaml("temp", "Selected Container", selected)
        print(f"Dropdown selected: {selected}")

        container_config = self.config["Containers"].get(selected, {})

        for key, entry_data in self.entries.items():
            config_key = entry_data["config_key"]
            param_var = entry_data["var"]
            entry_widget = entry_data["widget"]
            state = entry_data["state"]

            # Update only if the key exists in the container config
            if config_key in container_config:
                new_val = container_config[config_key]

                # Allow modification if currently read-only
                if entry_widget['state'] == 'readonly':
                    entry_widget.configure(state='normal')

                param_var.set(str(new_val))

                # Restore readonly if necessary
                if state == "readonly":
                    entry_widget.configure(state='readonly')
        # Handle the selection logic here if needed (e.g., update UI or config)
        return


    def add_entries(self):
        """
        def: This function adds all the entries in the Parameter Frame
        :return: ---
        """
        self.entry_frame = tk.Frame(self, bg="lightgreen")
        self.entry_frame.pack(fill=tk.BOTH, expand=True)

        self.entries = {
            "Maximum Volume [ul]:":         [self.config["Maximum Volume"], "Maximum Volume", "readonly"],              # Structure: {label: [initial value, config key, state]}
            "Attachment Volume [ul]:":      [self.config["Maximum Volume"], "Attachment Volume", "normal"],
            "fill Flow [ul/min]:":          [self.config["fill"], "fill", "normal"],
            "attachment Flow [ul/min]:":    [self.config["attachment"], "attachment", "normal"],
            "empty Flow [ul/min]:":         [self.config["empty"], "empty", "normal"],
            "add Flow [ul/min]:":           [self.config["add"], "add", "normal"],
            "remove Flow [ul/min]:":        [self.config["remove"], "remove", "normal"],
            "add/remove Volume [ul]:":      [self.config["Small Volume"], "Small Volume", "normal"]}

        row = 0
        for key, (value, config_key, state) in self.entries.items():                                                    # Iterate through entries
            param_label = tk.Label(self.entry_frame, text=key, bg="lightgreen")
            param_label.grid(row=row, column=0, padx=5, pady=5, sticky="e")

            param_var = tk.StringVar()                                                                                  # Generate a stringVar for each entry, this allows manipulation later
            param_var.set(str(value))                                                                                   # Set the string variable

            entry = tk.Entry(self.entry_frame, textvariable=param_var, width=20, state=state)                           # This line creates the entry
            entry.bind("<Return>", partial(self.on_enter, key=config_key, var=param_var))                               # Bind the confirmation to <Return>
            entry.bind("<FocusIn>", lambda event, e=param_var, k=config_key, s=state: self.set_active_entry(e, k, s))   # Remember which entry is focused, this allows manipulation with the turning knob

            entry.grid(row=row, column=1, padx=5, pady=5)                                                               # Place on grid

            self.entries[key] = {"var": param_var, "config_key": config_key, "state": state, "widget": entry}
            self.entry_states[key] = state                                                                              # Store state alongside the entry
            row += 1
        return

    def set_active_entry(self, entry_var,config_key, state):
        """
        def: This function tracks the currently active entry. This is later used for manipulation with the turning knob.
        :param entry_var: PyVar which is the entry that is focused
        :param config_key: String, which is the key in the yaml file
        :param state: String, which can be editable or non-editable
        :return:---
        """
        if state != "readonly":
            self.active_entry = {"var": entry_var, "config_key": config_key}
        else:
            self.active_entry = None                                                        # Ignore readonly entries
        return

    def on_enter(self,event, key, var):
        """
        def: This method is called when Enter is pressed in any entry and
             updates the yaml file and the temp dict with the new value from the entry.
        :param key: String, which is the key of the temp dict
        :param var: pyVar, which is the entry variable which is changed
        :return:
        """
        self.config[key] = var.get()                                                        # Update the temp dictionary with the new value
        self.writer.update_yaml(which="config", key=key, new_value=self.config[key])        # Write the new value to the yaml file
        return

    def add_buttons(self):
        """
        def: This function creates the buttons in the button_frame
             which is the lower part of the main_frame
        :return:---
        """
        self.button_frame = tk.Frame(self, bg="lightgreen")                     # Buttons in the lower part of ParameterFrame
        self.button_frame.pack(fill=tk.BOTH, expand=True)

        self.button_func = {                                                    # Defines a dict which holds the functions of the buttons
                        "Fill":         self.experiment.fill,
                        "Attachment":   self.experiment.attachment,
                        "Empty":        self.experiment.empty,
                        "Add":          self.experiment.add,
                        "Remove":       self.experiment.remove,
                        "Pause/Resume": self.experiment.pause,
                        "Venting":      self.experiment.vent,
                        "Automatic":    None}
        self.buttons = {}

        for idx, (key, func) in enumerate(self.button_func.items()):                                                                                # generate the buttons
            if key != "Automatic":
                button = tk.Button(self.button_frame, text=key, command=partial(self.start_callback, func) if func else self.start_callback, width=12)
            else:
                button = tk.Button(self.button_frame, text=key, command=self.automatic_callback, width=12)
            button.grid(row=idx // 3, column=idx % 3, padx=5, pady=5)
            self.buttons[key] = button                                                                                                              # store the buttons in a dict so that they are accessible

        zero_volume_button = tk.Button(self.button_frame, text="Set Volume to Zero", command=self.set_volume_to_zero, width=15)                     # This button is used to set the current vessel volume to zero
        zero_volume_button.grid(row=(len(self.button_func) // 3) + 1, column=0, columnspan=3, padx=5, pady=5)
        self.buttons["Set Volume to Zero"] = zero_volume_button                                                                                     # Add the new button to the buttons dictionary

        set_bottle_volume_button = tk.Button(self.button_frame, text="Set Bottle Volume", command=self.open_set_bottle_volume_window, width=15)     # This button is used to set the volume in the bottle
        set_bottle_volume_button.grid(row=(len(self.button_func) // 3) + 2, column=0, columnspan=3, padx=5, pady=5)
        self.buttons["Set Bottle Volume"] = set_bottle_volume_button

        return

    def set_volume_to_zero(self):
        """
        def: Sets the current vessel volume to zero.
        """
        self.temp.update({"Current Vessel Volume": 0})                                                          # set temp to zero, since parameter and state variable frame are both using the same instance this works
        self.state_variable_frame.update_variables()                                                            # Update entries in the state parameter frame
        messagebox.showinfo("Volume Reset", "The current vessel volume has been set to zero.")     # Confirm with a message
        return

    def open_set_bottle_volume_window(self):
        """
        def: This function opens another window where the new volume in the bottle can be set.
        """
        window = tk.Toplevel(self)                                              # create a new window
        window.title("Set Bottle Volume")
        window.geometry("300x150")
        window.resizable(False, False)

        tk.Label(window, text="Enter Bottle Volume (ml):").pack(pady=10)        # Create the label for the entry
        bottle_volume_var = tk.StringVar()                                      # Create a variable for the entry which can be manipulated
        entry = tk.Entry(window, textvariable=bottle_volume_var, width=20)      # Create the entry
        entry.pack(pady=5)

        def set_bottle_volume():
            """
            def: This function sets the new volume of the bottle
            """
            try:
                bottle_volume = float(bottle_volume_var.get())                                          # Get the variable of the entry
                self.temp["Bottle Volume"] = bottle_volume                                              # Update config
                self.state_variable_frame.update_variables()                                            # Update state variable frame

                messagebox.showinfo("Success", "Bottle volume updated successfully!")      # Sent a message
                window.destroy()                                                                        # Close the window
            except ValueError:
                messagebox.showerror("Error", "Please enter a valid number.")
            return

        entry.bind("<Return>", lambda event: set_bottle_volume())                                       # Confirm with enter
        tk.Button(window, text="Confirm", command=set_bottle_volume).pack(pady=10)                      # Or confirm with the confirm button
        return

class StateVariableFrame(tk.LabelFrame):
    """
    def: This class displays all the important state variables during the measurement
    """
    def __init__(self, root, writer, experiment, yaml_file):
        super().__init__(root, text="State Variables", borderwidth=2, relief="groove", bg="khaki")      # Set frame color and title

        self.experiment = experiment
        self.writer = writer
        self.yaml_file = yaml_file
        self.config = self.writer.read_yaml("config")[0]

        self.entry_frame = tk.Frame(self, bg="khaki")           # Set color
        self.entry_frame.grid(row=0, column=0, sticky="nsew")  # Use grid instead of pack

        self.entries = None

        self.checkboxes = {}
        self.valves = {}
        self.add_entries()                                      # Add the entries
        self.add_checkboxes()                                   # Add the checkboxes
        self.add_progressbar()                                  # Add the progress bar at the bottom
        return

    @property
    def temp(self):
        return self.experiment.temp                             # Get the 'temp' dictionary from the experiment instance

    @temp.setter
    def temp(self, value):
        if isinstance(value, dict):                             # If 'value' is a dictionary, update experiment.temp
            self.experiment.temp.update(value)                  # Update existing dictionary with new values
        else:
            raise ValueError("temp must be a dictionary or dictionary-like object")

    def block_interaction(self):
        """Dummy function to block the interaction with the checkboxes"""
        return "break"

    def add_checkboxes(self):
        """
        def: This function adds checkboxes for boolean state variables.
        :return:---
        """
        self.checkboxes = {"Paused":   {"var": None, "config_key": "Is Paused"},        # Create a dict for the checkboxes and the config key
                           "Running":  {"var": None, "config_key": "Is Running"}}

        self.valves = {"Venting Valve": {"var": None, "config_key": "V1"},
                       "Water Valve": {"var": None, "config_key": "V2"},
                       "Opening Valve": {"var": None, "config_key": "V3"},}

        row = 10                                                            # Row counter for grid placement
        col = 0                                                             # Start placing in the first column

        for label_text, valve_details in self.valves.items():
            param_var = tk.BooleanVar()
            config_key = valve_details["config_key"]                                    # Use the config_key for addressing values


            if config_key not in self.temp:                                         # Ensure self.temp has the required key for config_key
                self.temp[config_key] = False                                       # Initialize with a default value

            initial_value = self.temp.get(config_key, False)                        # Retrieve initial state
            param_var.set(initial_value)


            valve_details["var"] = param_var                                        # Update the valve dictionary with the BooleanVar, keeping the original config_key


            checkbox = tk.Checkbutton(self.entry_frame, text=label_text, variable=param_var, bg="khaki")        # Create and place the checkbox
            checkbox.grid(row=row, column=col, padx=5, pady=5, sticky="w")
            checkbox.bind("<Button-1>", lambda event: self.block_interaction())     # Block interaction

            col += 1                                                                # Move to the next column for the next valve checkbox

        row += 1                                                                    # Add checkboxes for 'Paused' and 'Running' in the second row
        col = 0                                                                     # Reset column placement
        
        for label_text, checkbox_details in self.checkboxes.items():
            param_var = tk.BooleanVar()
            config_key = checkbox_details["config_key"]                                 # Use the config_key for addressing values


            if config_key not in self.temp:                                             # Ensure self.temp has the required key for config_key
                self.temp[config_key] = False                                           # Initialize with a default value

            initial_value = self.temp.get(config_key, False)                            # Retrieve initial state
            param_var.set(initial_value)


            checkbox_details["var"] = param_var                                         # Update the checkboxes dictionary with the BooleanVar, keeping the original config_key


            checkbox = tk.Checkbutton(self.entry_frame, text=label_text, variable=param_var, bg="khaki")        # Create and place the checkbox
            checkbox.grid(row=row, column=col, padx=5, pady=5, sticky="w")
            checkbox.bind("<Button-1>", lambda event: self.block_interaction())         # Block interaction

            col += 1                                                                    # Move to the next column

    def add_entries(self):
        """
        def: This function add the entries.
        :return:
        """
        self.entries = {                                                                    # Create a dict which contains a string variable for the entries and the config key
            "Current Vessel Volume [ul]:":      {"var": None, "config_key": "Current Vessel Volume"},
            "Final Volume [ul]:":               {"var": None, "config_key": "Final Volume"},
            "Remaining Volume [ul]:":           {"var": None, "config_key": "Remaining Volume"},
            "Current Flow [ul/min]:":           {"var": None, "config_key": "Current Flow"},
            "Set Flow [ul/min]:":               {"var": None, "config_key": "Set Flow"},
            "Current Pressure [mbar]:":         {"var": None, "config_key": "Current Pressure"},
            "Operation:":                       {"var": None, "config_key": "Operation"},
            "Remaining Bottle Volume [ml]:":    {"var": None, "config_key": "Bottle Volume"}}

        row = 0                                                                             # Row counter for grid placement
        for label_text, details in self.entries.items():                                    # Iterate through the entry dict

            param_label = tk.Label(self.entry_frame, text=label_text, bg="khaki")           # Create label
            param_label.grid(row=row, column=0, padx=5, pady=5, sticky="e")

            param_var = tk.StringVar()                                                      # Create StringVar and bind it to an Entry
            initial_value = self.temp.get(details["config_key"], "N/A")                     # Set the initial value, if unknown set to N/A
            if isinstance(initial_value, (int, float)):
                initial_value = round(initial_value, 2)                                     # Limit the number to 2 decimal places
            param_var.set(str(initial_value))

            details["var"] = param_var                                                      # Store the StringVar

            entry = tk.Entry(self.entry_frame, textvariable=param_var, width=20, state='readonly')      # Create entry and bind it to the StringVar
            entry.grid(row=row, column=1, padx=5, pady=5)                                               # place the entry on the grid

            row += 1                                                                        # Move to the next row for the next entry
        return

    def add_progressbar(self):
        """
        def: This function adds a progress bar at the bottom of the frame.
        :return:
        """
        self.entry_frame.grid_rowconfigure(100, weight=1)  # Adjust this number to a row number near the bottom

        # Create and pack the progress bar
        self.progress_bar = ttk.Progressbar(self, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.grid(row=100, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        self.progress_label = tk.Label(self, text="Remaining Time: 0, Progress: 0%", bg="khaki")
        self.progress_label.grid(row=101, column=0, columnspan=2, padx=10, pady=10, sticky="n")
        return

    def update_variables(self):
        """
        def: This function updates the entries and checkboxes in this frame during the measurement.
        :return:
        """
        for label_text, details in self.entries.items():                # Update entries
            value = self.temp.get(details["config_key"], "N/A")         # Retrieve the value from self.temp using the config_key
            if isinstance(value, (int, float)):
                value = round(value, 2)                                 # Limit the number to 2 decimal places
            details["var"].set(str(value))                              # Update the StringVar with the new value

        for label_text, details in self.checkboxes.items():             # Update checkboxes
            value = self.temp.get(details["config_key"], False)         # Retrieve the value for the checkbox from self.temp
            details["var"].set(value)                                   # Update the BooleanVar with the new value

        for label_text, details in self.valves.items():                 # Update valve checkboxes
            value = self.temp.get(details["config_key"], False)         # Retrieve the value for the valve checkbox from self.temp
            details["var"].set(value)                                   # Update the BooleanVar with the new value

        with open(self.yaml_file, 'w') as file:                         # Write the current state to the YAML file
            yaml.dump(self.temp, file)

        self.progress()
        self.after(100, self.update_variables)                      # Refresh every 100ms
        return

    def progress(self):
        """
        def: This function updates the progress bar based on the remaining PVA time.
        :return:
        """
        remaining_time = self.temp["Remaining PVA Time"]                # Get the remaining PVA time from the temp dictionary

        remaining_timedelta = datetime.timedelta(seconds=remaining_time)

        # Format the remaining time as hh:mm:ss
        formatted_time = str(remaining_timedelta).split(".")[0]  # Split at the decimal and keep only the time part (hh:mm:ss)

        max_time = self.config["PVA Waiting Time"]*60                                                  # Get the waiting time
        progress = (1 - remaining_time / max_time) * 100                # Convert remaining time into progress

        self.progress_bar["value"] = progress
        self.progress_label.config(text=f"Remaining Time: {formatted_time}, Progress: {progress:.2f}%")
        self.update_idletasks()
        return

class MainApplication(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("GUI Layout with Frames and Titles")
        #self.geometry("1000x400")

        self.project_frame = None
        self.main_frame = None
        self.parameter_frame =None
        self.state_variable_frame = None

        self.key_bindings = None

        stop_event.clear()
        self.current_thread = None
        self.current_function = None

        self.project = project
        self.writer = Configurator.WritingManager(project)
        self.experiment = Experiment.Experimentator(self.writer)                                # Important, when using this code and the self.temp.update,
                                                                                                # it is important that there is no more than one instance of Experimentator()
                                                                                                # as otherwise the cross-linking of MainApplication.temp and Experimentator.temp is not correct

        self.config, _ = self.writer.read_yaml("both")
        self.yaml_file = os.path.join(self.config["Project Path"],"4_Config","temp.yaml")      # For debugging reasons the file is called temp_test

        pause_event.clear()
        self.temp.update({"Is Paused": pause_event.is_set()})

        measurement_event.clear()
        self.temp.update({"Is Running": measurement_event.is_set()})

        self.add_project_frame()                                            # Add project frame
        self.add_main_frame()                                               # Add main frame
        self.keyboard_binding()                                             # Add keyboard bindings
        return

    @property
    def temp(self):
        return self.experiment.temp                                         # Get the 'temp' dictionary from the experiment instance

    @temp.setter
    def temp(self, value):
        if isinstance(value, dict):                                         # If 'value' is a dictionary, update Exp.temp
            self.experiment.temp.update(value)                              # Update existing dictionary with new values
        else:
            raise ValueError("temp must be a dictionary or dictionary-like object")

    def add_project_frame(self):
        self.project_frame = ProjectFrame(self)                             # Call project frame class
        self.project_frame.pack(fill=tk.X, padx=10, pady=5)
        return

    def add_main_frame(self):
        self.main_frame = tk.Frame(self)                                    # Create a frame
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.add_state_variable_frame()                                     # Add state variable frame
        self.add_parameter_frame()                                          # Add parameter frame
        return

    def add_parameter_frame(self):
        self.parameter_frame = ParameterFrame(self.main_frame, self.state_variable_frame, self.config, self.writer, self.experiment, self.handle_key_event, self.start_automatic)    # Call parameter class with callback to start_measurement
        self.parameter_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        return

    def add_state_variable_frame(self):
        self.state_variable_frame = StateVariableFrame(self.main_frame, self.writer, self.experiment, self.yaml_file)   # Call state variable class with yaml_path
        self.state_variable_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        return

    def keyboard_binding(self):
        """
        def: This function sets up the keyboard bindings.
        :return:
        """
        self.key_bindings = {                           # Dict which holds the function to be called
            "<KeyPress-1>": self.experiment.fill,
            "<KeyPress-2>": self.experiment.attachment,
            "<KeyPress-3>": self.experiment.empty,
            "<KeyPress-4>": self.experiment.add,
            "<KeyPress-5>": self.experiment.remove,
            "<KeyPress-6>": self.experiment.pause,
            "<MouseWheel>": self.adjust_flow,
            "<Button-2>":   self.confirm_flow
        }

        for key, func in self.key_bindings.items():
            if key in ["<MouseWheel>", "<Button-2>"]:               # Pass the event for these bindings
                self.bind(key, func)                                # random comment, no use
            else:
                self.bind(key, lambda event, f=func: self.handle_key_event(f))
        return

    def _disable_buttons(self):
        """
        Disable all buttons except for the 'Pause/Resume' button.
        """
        for key, button in self.parameter_frame.buttons.items():
            if key != "Pause/Resume":                                             # Keep the 'Pause/Resume' button enabled
                button.config(state=tk.DISABLED)
        return

    def _enable_buttons(self):
        """
        Re-enable all buttons.
        """
        for button in self.parameter_frame.buttons.values():
            button.config(state=tk.NORMAL)
        return

    def _disable_keyboard_bindings(self):
        """
        Disable all keyboard bindings except for the 'Pause/Resume' key.
        """
        for key in self.key_bindings.keys():
            if key != "<KeyPress-6>":                                           # Keep the 'Pause/Resume' key enabled
                self.unbind(key)
        return

    def _enable_keyboard_bindings(self):
        """
        def: Re-enable all keyboard bindings.
        """
        for key, func in self.key_bindings.items():
            if key in ["<MouseWheel>", "<Button-2>"]:                       # Pass the event for these bindings
                self.bind(key, func)
            else:
                self.bind(key, lambda event, f=func: self.handle_key_event(f))
        return

    def _disable_entries(self):
        """
        def: Disable all entries except for 'Pause/Resume'.
        """
        for label, entry_data in self.parameter_frame.entries.items():
            entry_widget = entry_data["widget"]                             # This is the reference to the Tkinter Entry widget
            entry_widget.config(state=tk.DISABLED)                          # Disable the entry widget
        return

    def _enable_entries(self):
        """
        def: Re-enable all entries.
        """
        for label, entry_data in self.parameter_frame.entries.items():
            entry_widget = entry_data["widget"]                             # This is the reference to the Tkinter Entry widget
            if entry_data["state"] != "readonly":                           # Keep readonly entries unaffected
                entry_widget.config(state=tk.NORMAL)                        # Enable the entry widget
        return

    def _disable_dropdown(self):
        self.parameter_frame.dropdown_menu.config(state=tk.DISABLED)
        return

    def disable_widgets(self):
        """
        def: This function disables all widgets.
        """
        self._disable_dropdown()
        self._disable_entries()
        self._disable_buttons()
        self._disable_keyboard_bindings()
        return

    def enable_widgets(self):
        """
        def: This function enables all widgets.
        """
        self._enable_entries()
        self._enable_buttons()
        self._enable_keyboard_bindings()
        return

    def adjust_flow(self, event):
        """
        def: This function adjusts the value of the currently active entry using the mouse wheel.
        """
        if not self.parameter_frame.active_entry:                                               # If no entry is chosen then nothing happens
            return

        try:
            current_value = int(self.parameter_frame.active_entry["var"].get())                 # Get the current value
            step = 1000                                                                         # Step size of the set_flow in [uL/min]
            new_value = current_value - step if event.delta > 0 else current_value + step       # Change the set_flow depending on wheel turning direction
            self.parameter_frame.active_entry["var"].set(str(new_value))                        # Set new variable
            print(f"Adjusted value: {new_value}")

        except ValueError as e:
            print(f"Invalid value in active entry: {e}")
        return

    def confirm_flow(self, event):
        """
        def: This function confirms the value of the currently active entry.
        """
        if not self.parameter_frame.active_entry:                                               # If no entry is chosen then nothing happens
            return

        try:
            active_entry = self.parameter_frame.active_entry
            confirmed_value = int(active_entry["var"].get())                                    # Get the current value

            config_key = active_entry["config_key"]                                             # Use the correct config key
            self.config[config_key] = confirmed_value                                             # Set the new value
            self.writer.update_yaml(which="config", key=config_key, new_value=confirmed_value)  # Write the new value in the config file

            print(f"Confirmed and stored: {config_key} = {confirmed_value}")
        except ValueError as e:
            print(f"Error confirming value: {e}")
        return


    def start_measurement(self, protocol_func, callback=None):
        """
        def: This function starts measurement in a separate thread.
        :param protocol_func: function that is run by this function.
        :param callback: function that is run at the end of this function if passed.
        """
        if stop_event.is_set():                                             # This condition should never be true, if it is then there is a bug
            print("Stopping variable is still set, thus returning")
            return
        if protocol_func != self.experiment.pva_waiting:
            print(f"Starting measurement")
            self.temp.update({"Set Flow": self.config[protocol_func.__name__]})
        self.temp.update({"Operation": protocol_func.__name__})

        measurement_event.set()                                             # Set the measurement_event
        self.temp.update({"Is Running": measurement_event.is_set()})        # Update temp

        self.current_thread = threading.Thread(target=self.run_measurement, args=(protocol_func,callback), daemon=True)     # The new thread is created

        self.current_thread.start()                                         # Start the new thread
        self.current_function = protocol_func                               # Place the protocol_func in the new thread

        self.disable_widgets()                                              # Disable all widgets so no other protocol can be called

        self.state_variable_frame.update_variables()                        # Start updating the state variable frame continuously
        return

    def run_measurement(self, protocol_func, callback):
        """
        def: This function is an intermediate step. It allows to use the MainApplication objects and calls the experiment function. It is in a separate thread.
        :param protocol_func: function that is run by this function.
        :param callback: function that is run at the end of this function if passed.
        """
        print(f"Running measurement, {protocol_func.__name__}")
        protocol_func()                                                     # Run the protocol function

        self.enable_widgets()                                               # Enable the widgets again

        measurement_event.clear()                                           # Only clear if the measurement has actually finished or stopped
        self.temp.update({"Is Running": measurement_event.is_set()})
        print(f"Measurement finished")

        if callback:
            callback()                                                      # Runs a subsequent function if passed
        return

    def toggle_pause(self, func=None):
        """
        def: This function toggles the pause state.
        """
        if pause_event.is_set():
            pause_event.clear()                                             # Resume to the measurement by clearing the pause event
            measurement_event.set()                                         # and by setting the measurement event
            self.disable_widgets()                                          # Disable all widgets
            print("Measurement resumed")
        else:
            pause_event.set()                                               # Pause the measurement by setting the pause event
            measurement_event.clear()                                       # and by clearing the measurement event
            self.enable_widgets()                                           # Enable all widgets
            print("Measurement paused")

        self.temp.update({"Is Paused": pause_event.is_set()})               # Update the temp
        self.temp.update({"Is Running": measurement_event.is_set()})
        func()                                                              # Call the pause function in the experiment script to handle the valve states
        return

    def stop_measurement(self):
        """
        def: This function stops the measurement when coming from the pause state.
        """
        print(f"current function {self.current_function}")
        if self.current_thread and self.current_thread.is_alive():
            print(f"Stopping {self.current_function.__name__}...")

            stop_event.set()                                                # Signal the current function to stop

            pause_event.clear()                                             # Reset the pause event
            self.temp.update({"Is Paused": pause_event.is_set()})

            self.current_thread.join(5)                                     # Wait for the current thread to finish only after stopping the function

            if self.current_thread.is_alive():                              # After the thread has joined, check if it's still alive
                print(f"{self.current_function.__name__} did not stop in time, ignoring this from now on.")         # If this message is printed then something is not working right. But it's annoying to deal with.
            else:
                print(f"{self.current_function.__name__} stopped.")

            self.enable_widgets()                                          # Disable all widgets
            self.current_thread = None                                      # Reset the thread
            self.current_function = None                                    # Reset the current function
            stop_event.clear()                                              # Clear the stop event
        return

    def start_automatic(self):
        """
        def: This function starts the automatic cleaning process. It fills the Vessel if empty, waits a set time and then empties the vessel again.
        """
        if stop_event.is_set():                                             # This condition should never be true, if it is then there is a bug
            print("Stopping variable is still set, thus returning")
            return

        self.start_measurement(self.experiment.fill, callback=self.start_pva_waiting)
        return

    def start_pva_waiting(self):
        """
        def: This function starts the waiting process for the PVA to dissolve.
        """
        messagebox.showinfo("Information","The Vessel is now filled. Click OK to start the waiting time.")
        self.start_measurement(self.experiment.pva_waiting, callback=lambda: self.start_measurement(self.experiment.empty))       # Stars the waiting function and passes subsequent function
        return

    def handle_key_event(self, func):
        """
        def: Handle key press events, especially for pause and set_flow adjustment.
        :param func: A function being passed to this one and then passed further or executed.
        :returns: ---
        """
        if func == self.experiment.pause:
            self.toggle_pause(func)
        elif func == self.adjust_flow or func == self.confirm_flow:
            func()
            print(f'Flow of {func.__name__} is {self.config[func.__name__]}')
        elif func:                                                              # If a function is triggered that is not 'pause' nor the special set_flow change functions
            if self.current_thread is not None:
                self.stop_measurement()                                         # Stop current measurement if paused
            print(func.__name__)
            self.start_measurement(func)                                    # Start the new function
        return


if __name__ == "__main__":
    app = MainApplication()
    app.mainloop()
