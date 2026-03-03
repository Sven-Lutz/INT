from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton


class HoldButton(QPushButton):
    """
    Momentary / dead-man switch QPushButton.

    Guarantees:
    - never checkable / never toggles
    - hold_started emitted exactly once per hold
    - hold_ended emitted exactly once per hold
    - leaving the widget while holding triggers hold_ended (safety)
    """

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

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton and not self._holding and self.isEnabled():
            self._holding = True
            self.hold_started.emit()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._end_hold_if_needed()
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        # Safety: cursor left widget while holding -> stop immediately.
        self._end_hold_if_needed()
        super().leaveEvent(e)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        # If someone disables the button mid-hold -> force stop.
        if not enabled:
            self._end_hold_if_needed()
        super().setEnabled(enabled)
