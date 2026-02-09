import sys
import PySide6.QtWidgets as qtw
from PySide6.QtCore import Qt


class TopFrame(qtw.QFrame):
    def __init__(self, path: str):
        super().__init__()
        self.setFrameShape(qtw.QFrame.Box)
        self.setMinimumHeight(60)

        layout = qtw.QHBoxLayout(self)
        self.path_display = qtw.QLineEdit()
        self.path_display.setReadOnly(True)
        self.path_display.setText(path)
        self.path_display.setStyleSheet("background-color: #f0f0f0;")

        layout.addWidget(self.path_display)

    def set_path(self, path: str):
        self.path_display.setText(path)

    def get_path(self) -> str:
        return self.path_display.text()

class LeftFrame(qtw.QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(qtw.QFrame.Box)

        layout = qtw.QVBoxLayout(self)
        layout.addWidget(qtw.QLabel("Left Panel Content"))

class RightFrame(qtw.QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(qtw.QFrame.Box)

        layout = qtw.QVBoxLayout(self)
        layout.addWidget(qtw.QLabel("Right Panel Content"))

class MainWindow(qtw.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modular GUI App")
        self.resize(800, 600)

        central_widget = qtw.QWidget()
        self.setCentralWidget(central_widget)

        main_layout = qtw.QVBoxLayout(central_widget)

        # Instantiate frame components
        self.top_frame = TopFrame("/your/path/here")
        self.left_frame = LeftFrame()
        self.right_frame = RightFrame()

        # Top Frame
        main_layout.addWidget(self.top_frame)

        # Bottom Splitter
        splitter = qtw.QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left_frame)
        splitter.addWidget(self.right_frame)
        splitter.setSizes([400, 400])

        main_layout.addWidget(splitter)
        main_layout.setStretch(0, 0)  # Top frame: minimal
        main_layout.setStretch(1, 1)  # Bottom frames: expand


if __name__ == "__main__":
    app = qtw.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
