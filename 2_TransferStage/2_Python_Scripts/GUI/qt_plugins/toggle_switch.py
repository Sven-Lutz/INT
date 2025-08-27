# toggle_switch.py
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, QPropertyAnimation, Property, Signal
from PySide6.QtGui import QPainter, QColor, QBrush

class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 30)
        self._checked = False
        self._circle_position = 2

        self._animation = QPropertyAnimation(self, b"circle_position", self)
        self._animation.setDuration(200)

        self._checked_color = QColor("#00C853")
        self._unchecked_color = QColor("#ccc")
        self._circle_color = QColor("#fff")

        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.setChecked(not self._checked)

    def setChecked(self, checked: bool):
        if self._checked == checked:
            return
        self._checked = checked
        start = self._circle_position
        end = self.width() - self.height() + 2 if self._checked else 2
        self._animation.setStartValue(start)
        self._animation.setEndValue(end)
        self._animation.start()
        self.toggled.emit(self._checked)
        self.update()

    def isChecked(self):
        return self._checked

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg_color = self._checked_color if self._checked else self._unchecked_color
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.NoPen)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.drawRoundedRect(rect, self.height() / 2, self.height() / 2)

        radius = self.height() - 4
        painter.setBrush(QBrush(self._circle_color))
        painter.drawEllipse(QRectF(self._circle_position, 2, radius, radius))

    def get_circle_position(self):
        return self._circle_position

    def set_circle_position(self, pos):
        self._circle_position = pos
        self.update()

    circle_position = Property(float, get_circle_position, set_circle_position)
