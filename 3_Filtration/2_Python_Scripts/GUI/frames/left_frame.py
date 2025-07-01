from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QLineEdit

class LeftFrame(QFrame):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.param_input = QLineEdit()
        self.param_input.setPlaceholderText("Enter experiment parameter")

        self.start_button = QPushButton("Start Experiment")

        layout.addWidget(self.param_input)
        layout.addWidget(self.start_button)
