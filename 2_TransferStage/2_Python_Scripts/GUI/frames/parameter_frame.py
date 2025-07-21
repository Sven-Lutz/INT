from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QLabel, QComboBox
from PySide6.QtCore import Qt

class ParameterFrame(QFrame):
    def __init__(self, config):
        super().__init__()
        layout = QVBoxLayout(self)

        label = QLabel("Parameters")
        label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px; background-color: lightblue;")
        label.setAlignment(Qt.AlignTop)

        self.setStyleSheet("background-color: lightblue;")

        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.status_label = QLabel("Status: Idle")
        self.measurement_label = QLabel("Measurement: 0.0")
        self.experiment_select = QComboBox()
        self.experiment_select.addItems(["add", "remove", "fill", "empty", "automatic"])
        self.experiment_select.setFixedWidth(120)

        layout.addWidget(label)
        layout.addWidget(self.experiment_select)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.measurement_label)
        self.setLayout(layout)

    def selected_experiment(self):
        return self.experiment_select.currentText()

    def set_status(self, text):
        self.status_label.setText(f"Status: {text}")

    def set_measurement(self, value):
        self.measurement_label.setText(f"Measurement: {value:.2f}")