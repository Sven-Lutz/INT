# src/gui/widgets/phase_card.py
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
    QFormLayout,
)


class PhaseCard(QFrame):
    def __init__(self, title: str, parent: Optional[QWidget] = None, *, phase_key: str = "") -> None:
        super().__init__(parent)
        self.phase_key = (phase_key or "").strip().upper()

        self.setProperty("surface", "card")
        self.setProperty("phaseState", "idle")

        self._title = QLabel(title)
        self._title.setProperty("role", "title")
        self._title.setStyleSheet("font-family: 'Consolas', monospace; letter-spacing: 1px;")

        self._pill = QLabel("IDLE")
        self._pill.setProperty("role", "pill")
        self._pill.setAlignment(Qt.AlignCenter)

        header = QHBoxLayout()
        header.setContentsMargins(12, 12, 12, 8)
        header.setSpacing(8)
        header.addWidget(self._title, 1)
        header.addWidget(self._pill, 0, Qt.AlignRight)

        self._form = QFormLayout()
        self._form.setContentsMargins(12, 0, 12, 0)
        self._form.setHorizontalSpacing(14)
        self._form.setVerticalSpacing(8)

        self._hold_btn: Optional[QLabel] = None
        self._hold_help: Optional[QLabel] = None
        self._hold_allowed: bool = False
        self._hold_active: bool = False

        self._hint = QLabel("")
        self._hint.setProperty("role", "hint")
        self._hint.setWordWrap(True)

        footer = QVBoxLayout()
        footer.setContentsMargins(12, 8, 12, 12)
        footer.addWidget(self._hint)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(header)
        root.addLayout(self._form)
        root.addLayout(footer)

    def form(self) -> QFormLayout:
        return self._form

    def set_hint(self, text: str) -> None:
        self._hint.setText(text or "")

    def set_state(self, state: str, hint: str = "") -> None:
        s = (state or "idle").lower()
        label = s.upper()
        if s == "next":
            label = "NEXT"
        elif s == "active":
            label = "ACTIVE"
        elif s == "done":
            label = "DONE"
        elif s == "blocked":
            label = "BLOCKED"
        elif s == "idle":
            label = "IDLE"

        self._pill.setText(label)
        self.set_hint(hint)

        self.setProperty("phaseState", s)
        self._restyle()

    def enable_hold_indicator(self, *, label: str = "HOLD BACKWASH (SPACE)", help_text: str = "") -> None:
        if self._hold_btn is not None:
            return

        self._hold_btn = QLabel(label)
        self._hold_btn.setAlignment(Qt.AlignCenter)
        self._hold_btn.setProperty("role", "title")
        self._hold_btn.setObjectName("btnHold")
        self._hold_btn.setProperty("holdAllowed", "false")
        self._hold_btn.setProperty("holdActive", "false")

        self._hold_help = QLabel(help_text or "Hold SPACE to run. Release to stop.")
        self._hold_help.setWordWrap(True)
        self._hold_help.setProperty("role", "hint")

        self._form.addRow("", self._hold_btn)
        self._form.addRow("", self._hold_help)

        self._restyle()

    def set_hold_affordance(self, allowed: bool, hint: str = "") -> None:
        self._hold_allowed = bool(allowed)
        if self._hold_btn is not None:
            self._hold_btn.setProperty("holdAllowed", "true" if allowed else "false")
        if self._hold_help is not None and hint:
            self._hold_help.setText(hint)
        self._restyle()

    def set_hold_active(self, active: bool) -> None:
        self._hold_active = bool(active)
        if self._hold_btn is not None:
            self._hold_btn.setProperty("holdActive", "true" if active else "false")
        self._restyle()

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()