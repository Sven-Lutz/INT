from PySide6.QtWidgets import QFrame, QVBoxLayout, QProgressBar, QLabel
from PySide6.QtCore import Qt

class StateVariableFrame(QFrame):
    def __init__(self, initial_state):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.labels = {}
        self._build_ui(initial_state)


    def _build_ui(self, state):

        label = QLabel("State Variables")
        label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px; background-color: lightyellow;")
        label.setAlignment(Qt.AlignTop)
        self.layout.addWidget(label)

        for key, value in state.items():
            label = QLabel(f"{key}: {value}")
            self.layout.addWidget(label)
            self.labels[key] = label
            self.setStyleSheet("background-color: lightyellow;")

    def update_state(self, new_state):
        for key, value in new_state.items():
            if key in self.labels:
                self.labels[key].setText(f"{key}: {value}")
            else:
                label = QLabel(f"{key}: {value}")
                self.layout.addWidget(label)
                self.labels[key] = label
