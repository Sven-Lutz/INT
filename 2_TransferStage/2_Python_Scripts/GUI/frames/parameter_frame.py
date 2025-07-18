from PySide6.QtWidgets import QFrame, QVBoxLayout, QProgressBar, QLabel

class ParameterFrame(QFrame):
    def __init__(self, config):
        super().__init__()
        layout = QVBoxLayout(self)
        self.setStyleSheet("background-color: lightyellow;")

        self.progress = QProgressBar()
        self.status_label = QLabel("Idle")

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)