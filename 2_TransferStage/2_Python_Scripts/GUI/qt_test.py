from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile
from qt_plugins.toggle_switch import ToggleSwitch


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        loader = QUiLoader()
        loader.registerCustomWidget(ToggleSwitch)

        ui_file = QFile("widgets.ui")
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError("Failed to open GUI.ui")

        self.ui = loader.load(ui_file, self)
        ui_file.close()

        if not self.ui:
            raise RuntimeError("Failed to load UI")

        self.setCentralWidget(self.ui)

        # Use findChild to access toggleSwitch inside the loaded UI
        toggle = self.ui.findChild(ToggleSwitch, "toggleSwitch")
        if toggle:
            print("✅ ToggleSwitch found!", toggle.size())
            toggle.setStyleSheet("background: pink;")  # make it visible
        else:
            print("❌ ToggleSwitch not found")

    def toggle_changed(self, checked):
        print("Toggle switched:", "ON" if checked else "OFF")


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
