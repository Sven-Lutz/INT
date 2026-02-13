from PySide6.QtWidgets import QFrame, QLineEdit, QHBoxLayout


class TopFrame(QFrame):
    def __init__(self, config: dict):
        super().__init__()

        layout = QHBoxLayout(self)

        path = (
            config.get("Project Path")
            or config.get("project_path")
            or config.get("projectPath")
            or config.get("path")
            or ""
        )

        self.path_display = QLineEdit(str(path))
        self.path_display.setReadOnly(True)
        layout.addWidget(self.path_display)

    def set_path(self, path: str) -> None:
        self.path_display.setText(str(path))

    def get_path(self) -> str:
        return self.path_display.text()
