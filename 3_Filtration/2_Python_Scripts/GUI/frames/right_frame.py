from PySide6.QtWidgets import QFrame, QVBoxLayout, QProgressBar, QLabel

class RightFrame(QFrame):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.progress = QProgressBar()
        self.status_label = QLabel("Idle")

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)
