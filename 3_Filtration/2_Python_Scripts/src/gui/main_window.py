import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt

from frames.top_frame import TopFrame
from frames.left_frame import LeftFrame
from frames.right_frame import RightFrame
from utils.config_manager import ConfigManager

class MainWindow(Qtw.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Little Chonker")
        self.resize(800, 600)

        cfg_manager = ConfigManager()
        config = cfg_manager.load_config("general")

        central_widget = Qtw.QWidget()
        self.setCentralWidget(central_widget)
        layout = Qtw.QVBoxLayout(central_widget)

        self.top = TopFrame(config)
        self.left = LeftFrame(config)
        self.right = RightFrame(config)

        layout.addWidget(self.top)

        splitter = Qtw.QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left)
        splitter.addWidget(self.right)
        layout.addWidget(splitter)

        layout.setStretch(0, 0)
        layout.setStretch(1, 1)
