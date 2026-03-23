from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton


class HoldButton(QPushButton):
    """
    Kugelsicherer Momentary / Dead-Man Switch QPushButton.
    
    Guarantees:
    - Reagiert auf Maus (Klick) UND Tastatur (Leertaste).
    - hold_started / hold_ended feuern immer als striktes Paar.
    - leaveEvent oder disable bricht den Hold sofort ab (Sicherheit).
    """

    hold_started = Signal()
    hold_ended = Signal()

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCheckable(False)
        self.setAutoRepeat(False)
        self._holding = False

        # 🚀 Wir nutzen Qts native Signale (sind viel schneller und fangen auch Tastatur ab)
        self.pressed.connect(self._start_hold)
        self.released.connect(self._end_hold_if_needed)

    def _start_hold(self) -> None:
        if not self._holding and self.isEnabled():
            self._holding = True
            self.hold_started.emit()

    def _end_hold_if_needed(self) -> None:
        if self._holding:
            self._holding = False
            self.hold_ended.emit()

    def leaveEvent(self, e) -> None:
        # Safety: Maus verlässt das Widget während des Haltens -> sofortiger Stop.
        self._end_hold_if_needed()
        super().leaveEvent(e)

    def setEnabled(self, enabled: bool) -> None:
        # Safety: Wenn das System den Button deaktiviert -> sofortiger Stop.
        if not enabled:
            self._end_hold_if_needed()
        super().setEnabled(enabled)