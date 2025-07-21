from PySide6.QtWidgets import QFrame, QLineEdit, QHBoxLayout
import PySide6.QtWidgets as Qtw

class ProjectFrame(QFrame):
    def __init__(self,config):
        super().__init__()

        layout = QHBoxLayout(self)

        self.path_display = QLineEdit(config["Project Path"])
        self.path_display.setReadOnly(True)

        layout.addWidget(self.path_display)

        self.setSizePolicy(Qtw.QSizePolicy.Preferred, Qtw.QSizePolicy.Maximum)
        self.setStyleSheet("background-color: lightgreen;")
        return