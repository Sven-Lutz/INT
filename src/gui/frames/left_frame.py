from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QGridLayout, QPushButton,
    QLineEdit, QLabel
)

class LeftFrame(QFrame):
    def __init__(self, config):
        super().__init__()
        main_layout = QVBoxLayout(self)

        # Grid for name-value pairs
        grid = QGridLayout()
        self.value_fields = {}
        # Top input and button
        for row, (key, value) in enumerate(config.items()):
            if key == "Project Path":
                continue
            name_label = QLabel(f"{key}:")
            value_field = QLineEdit(str(value))  # or QLabel if read-only
            self.value_fields[key] = value_field

            grid.addWidget(name_label, row, 0)
            grid.addWidget(value_field, row, 1)

        self.start_button = QPushButton("Start Experiment")

        grid.addWidget(self.start_button, 10, 0, 1, 2)

        # Example parameters loaded from config (replace 'experiment1' as needed)


        self.value_fields = {}



        main_layout.addLayout(grid)
