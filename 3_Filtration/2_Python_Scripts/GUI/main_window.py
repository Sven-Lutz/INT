import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt

from frames.top_frame import TopFrame
from frames.left_frame import LeftFrame
from frames.right_frame import RightFrame

class MainWindow(Qtw.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Experiment Control")
        self.resize(800, 600)

        central_widget = Qtw.QWidget()
        self.setCentralWidget(central_widget)
        layout = Qtw.QVBoxLayout(central_widget)

        self.top = TopFrame("/current/project/path")
        self.left = LeftFrame()
        self.right = RightFrame()

        layout.addWidget(self.top)

        splitter = Qtw.QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left)
        splitter.addWidget(self.right)
        layout.addWidget(splitter)

        layout.setStretch(0, 0)
        layout.setStretch(1, 1)
