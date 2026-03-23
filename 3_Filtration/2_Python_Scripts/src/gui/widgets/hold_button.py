from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton


class HoldButton(QPushButton):

    hold_started = Signal()
    hold_ended = Signal()

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCheckable(False)
        self.setAutoRepeat(False)
        self._holding = False

    def _end_hold_if_needed(self) -> None:
        if self._holding:
            self._holding = False
            self.hold_ended.emit()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and not self._holding and self.isEnabled():
            self._holding = True
            self.hold_started.emit()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._end_hold_if_needed()
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e) -> None:  
        self._end_hold_if_needed()
        super().leaveEvent(e)

    def setEnabled(self, enabled: bool) -> None:
        if not enabled:
            self._end_hold_if_needed()
        super().setEnabled(enabled)
