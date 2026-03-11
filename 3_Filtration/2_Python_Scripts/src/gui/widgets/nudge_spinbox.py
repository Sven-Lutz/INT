from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QDoubleSpinBox, QPushButton, QSizePolicy

class NudgeSpinBox(QWidget):
    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, decimals: int, step: float, suffix: str, value: float):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setValue(value)
        self.spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        
        self.spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.spin.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        self.spin.setStyleSheet("""
            QDoubleSpinBox { 
                background: #050914; 
                border: 1px solid #1F2937; 
                color: #F8FAFC;
                border-radius: 4px;
                padding: 6px 10px;
                font-family: 'Consolas', monospace;
                font-weight: bold;
                font-size: 13px;
            } 
            QDoubleSpinBox:focus { border: 1px solid #8B5CF6; }
        """)

        btn_style = """
            QPushButton { 
                background-color: #111827; 
                color: #A0AEC0; 
                border: 1px solid #2D3748; 
                border-radius: 4px; 
                font-family: Arial, sans-serif; 
                font-size: 18px; 
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            } 
            QPushButton:hover { background-color: #2D3748; color: #FFFFFF; border-color: #8B5CF6; }
            QPushButton:pressed { background-color: #8B5CF6; color: #FFFFFF; border-color: #8B5CF6; }
            QPushButton:disabled { color: #4A5568; background-color: #050914; border-color: #111827; }
        """

        self.btn_m = QPushButton("-")
        self.btn_m.setFixedSize(30, 30)
        self.btn_m.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_m.setStyleSheet(btn_style)

        self.btn_p = QPushButton("+")
        self.btn_p.setFixedSize(30, 30)
        self.btn_p.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_p.setStyleSheet(btn_style)

        lay.addWidget(self.spin)
        lay.addWidget(self.btn_m)
        lay.addWidget(self.btn_p)

        self.btn_m.clicked.connect(lambda: self.spin.setValue(self.spin.value() - self.spin.singleStep()))
        self.btn_p.clicked.connect(lambda: self.spin.setValue(self.spin.value() + self.spin.singleStep()))
        self.spin.valueChanged.connect(self.valueChanged.emit)

    def value(self) -> float: return self.spin.value()

    def setValue(self, val: float): self.spin.setValue(val)

    def setEnabled(self, val: bool):
        super().setEnabled(val)
        self.spin.setEnabled(val)
        self.btn_m.setEnabled(val)
        self.btn_p.setEnabled(val)