from __future__ import annotations

from typing import Any, Mapping, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit


class TopFrame(QFrame):
    """
    Top bar displaying the resolved project path (read-only).

    Improvements:
    - Robust key normalization (case + underscore insensitive)
    - Clean layout margins
    - Defensive handling of non-string config values
    """

    _PATH_KEYS = {
        "project path",
        "project_path",
        "projectpath",
        "path",
    }

    def __init__(self, config: Optional[Mapping[str, Any]] = None):
        super().__init__()

        self._config = dict(config or {})

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self.path_display = QLineEdit()
        self.path_display.setReadOnly(True)
        self.path_display.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.path_display.setPlaceholderText("No project path configured")

        self._apply_path_from_config()

        layout.addWidget(self.path_display)

    # ---------------- Public API ----------------

    def set_path(self, path: str) -> None:
        self.path_display.setText(str(path or ""))

    def get_path(self) -> str:
        return self.path_display.text().strip()

    # ---------------- Internal helpers ----------------

    def _apply_path_from_config(self) -> None:
        path = self._extract_path(self._config)
        if path:
            self.path_display.setText(path)

    @classmethod
    def _extract_path(cls, config: Mapping[str, Any]) -> str:
        """
        Extract path from config using normalized key matching.
        Normalization:
        - lowercase
        - remove underscores
        - strip whitespace
        """
        for key, value in config.items():
            normalized = key.lower().replace("_", "").strip()
            if normalized in {k.replace("_", "") for k in cls._PATH_KEYS}:
                return str(value or "")
        return ""
