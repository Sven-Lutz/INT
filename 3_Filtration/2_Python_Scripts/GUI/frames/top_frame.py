from PySide6.QtWidgets import QFrame, QLineEdit, QHBoxLayout

class TopFrame(QFrame):
    def __init__(self,config):
        super().__init__()

        layout = QHBoxLayout(self)
        self.path_display = QLineEdit(config["Project Path"])
        self.path_display.setReadOnly(True)
        layout.addWidget(self.path_display)
