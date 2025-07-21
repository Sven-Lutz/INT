from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSplitter, QStackedLayout, QSizePolicy

from PySide6.QtCore import Qt

from frames.project_frame import ProjectFrame
from frames.parameter_frame import ParameterFrame
from frames.state_variable_frame import StateVariableFrame



class UiBuilder:
    @staticmethod
    def build_main_layout(window, config):
        central_widget = QWidget()
        window.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        project_frame = UiBuilder.build_project_frame(config)
        parameter_frame = UiBuilder.build_parameter_frame(config)
        state_variable_frame = UiBuilder.build_state_variable_frame(config)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(parameter_frame)
        splitter.addWidget(state_variable_frame)

        layout.addWidget(project_frame)
        layout.addWidget(splitter)

        return {
            "project_frame": project_frame,
            "state_variable_frame": state_variable_frame,
            "parameter_frame": parameter_frame,
            }

    @staticmethod
    def build_project_frame(config):
        return ProjectFrame(config)
    @staticmethod
    def build_state_variable_frame(config):
        return StateVariableFrame(config)
    @staticmethod
    def build_parameter_frame(config):
        return ParameterFrame(config)
