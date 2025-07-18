from PySide6.QtWidgets import QFrame, QVBoxLayout, QProgressBar, QLabel

class StateVariableFrame(QFrame):
    def __init__(self, initial_state):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.labels = {}
        self._build_ui(initial_state)


    def _build_ui(self, state):
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
