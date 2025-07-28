from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QLabel, QComboBox, QLineEdit, QGridLayout, QSizePolicy
from PySide6.QtCore import Qt

class ParameterFrame(QFrame):
    def __init__(self, config):
        super().__init__()
        layout = QVBoxLayout(self)


        label = QLabel("Parameters")
        label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px; background-color: lightblue;")
        label.setAlignment(Qt.AlignTop)
        layout.addWidget(label)

        self.setStyleSheet("background-color: lightblue;")

        self.grid = QGridLayout()

        self._status_Widget()
        self._experiment_handling()

        layout.addLayout(self.grid)
        self.setLayout(layout)


    def _status_Widget(self):
        self.status_label = QLabel("Status:")
        self.status_entry = QLineEdit("Idle")
        self.status_entry.setReadOnly(True)
        self.grid.addWidget(self.status_label, 5, 0, 1, 1)
        self.grid.addWidget(self.status_entry, 5, 1, 1, 1)
        return

    def _experiment_handling(self):
        self.experiment_select = QComboBox()
        self.experiment_select.addItems(["add", "remove", "fill", "empty", "automatic"])
        #self.experiment_select.setFixedWidth(240)

        self.start_button = QPushButton("Start")
        #self.start_button.setFixedWidth(120)
        #self.start_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        #self.start_button.setStyleSheet("font-size: 14px;")

        self.stop_button = QPushButton("Stop")
        #self.stop_button.setFixedWidth(120)
        #self.stop_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        #self.stop_button.setStyleSheet("font-size: 14px;")
        self.grid.setRowStretch(4, 10)
        self.grid.setSpacing(10)
        self.grid.addWidget(self.experiment_select, 2, 0, 1, 2)
        self.grid.addWidget(self.start_button, 3, 0, 1, 1)
        self.grid.addWidget(self.stop_button, 3, 1, 1, 1)


        return

    def selected_experiment(self):
        return self.experiment_select.currentText()

    def set_status(self, text):
        self.status_entry.setText(text)

    def set_measurement(self, value):
        self.measurement_label.setText(f"Measurement: {value:.2f}")