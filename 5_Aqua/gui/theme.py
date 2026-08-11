from __future__ import annotations

from PySide6.QtWidgets import QWidget


AQUA_STYLESHEET = """
QWidget {
    background: #f1f2f4;
    color: #20252b;
    font-family: "Segoe UI";
    font-size: 9pt;
}

QMainWindow {
    background: #e9ebee;
}

QLabel,
QCheckBox {
    background: transparent;
}

QFrame#headerFrame {
    background: #ffffff;
    border: 1px solid #c9ced3;
    border-radius: 3px;
}

QLabel#appTitle {
    color: #1f252b;
    font-size: 16pt;
    font-weight: 600;
}

QLabel#secondaryText {
    color: #69717a;
    font-size: 8pt;
}

QLabel[sampleContext="true"] {
    padding: 0 1px 2px 1px;
}

QLabel[sampleContext="true"][status="live"] {
    color: #386b49;
}

QLabel[sampleContext="true"][status="stale"] {
    color: #9a5900;
    font-weight: 600;
}

QLabel[sampleContext="true"][status="historical"] {
    color: #69717a;
    font-weight: 600;
}

QLabel[stateDisplay="true"] {
    background: #f7f8f9;
    border: 1px solid #c7ccd1;
    border-radius: 3px;
    padding: 4px 8px;
    font-size: 9pt;
    font-weight: 600;
}

QLabel[stateDisplay="true"][status="ready"] {
    color: #236b3d;
    border-color: #9cc8aa;
    background: #f1f8f3;
}

QLabel[stateDisplay="true"][status="running"] {
    color: #145b86;
    border-color: #9bbfd5;
    background: #f0f7fb;
}

QLabel[stateDisplay="true"][status="warning"] {
    color: #8a5200;
    border-color: #d7b777;
    background: #fff8e8;
}

QLabel[stateDisplay="true"][status="error"],
QLabel[stateDisplay="true"][status="fault"] {
    color: #a12622;
    border-color: #d8aaa7;
    background: #fff3f2;
}

QLabel[stateDisplay="true"][status="muted"],
QLabel[stateDisplay="true"][status="disconnected"] {
    color: #5f6770;
}

QLabel[telemetryIndicator="true"] {
    color: #7d858d;
    padding: 2px 4px;
    font-size: 8pt;
}

QLabel[telemetryIndicator="true"][status="live"] {
    color: #2d7a46;
}

QLabel[telemetryIndicator="true"][status="stale"] {
    color: #a15c00;
    font-weight: 600;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #c9ced3;
    border-radius: 3px;
    margin-top: 10px;
    padding: 8px 7px 7px 7px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: #343a40;
    background: #ffffff;
    font-size: 9pt;
}

QFrame#telemetryCard {
    background: #fbfbfc;
    border: 1px solid #d5d9dd;
    border-radius: 2px;
}

QFrame#telemetryCard[metricClickable="true"]:hover {
    background: #f2f7fb;
    border-color: #8eafc4;
}

QLabel#telemetryTitle {
    color: #68717a;
    font-size: 7.5pt;
    font-weight: 600;
}

QLabel#telemetryValue {
    color: #1f252b;
    font-size: 12.5pt;
    font-weight: 600;
}

QLabel#telemetryDetail {
    color: #6e7680;
    font-size: 8pt;
}

QFrame#telemetryCard[severity="warning"] {
    border-color: #d0ad6b;
    background: #fffaf0;
}

QFrame#telemetryCard[severity="error"] {
    border-color: #d5a09d;
    background: #fff5f4;
}

QFrame#telemetryCard[severity="ok"] {
    border-color: #a8cbb3;
}

QPushButton {
    min-height: 26px;
    padding: 2px 10px;
    border: 1px solid #aeb5bc;
    border-radius: 3px;
    background: #f7f8f9;
    color: #242a30;
    font-weight: 500;
}

QPushButton:hover {
    background: #eef1f3;
    border-color: #7d8994;
}

QPushButton:pressed {
    background: #e3e7ea;
}

QPushButton:disabled {
    color: #969da4;
    background: #f2f3f4;
    border-color: #d5d8db;
}

QPushButton#primaryButton {
    background: #eaf2f8;
    border-color: #7fa4bd;
    color: #174f70;
}

QPushButton#primaryButton:hover {
    background: #dcebf5;
}

QPushButton#startButton,
QPushButton#ledOnButton {
    background: #edf7f0;
    border-color: #78aa87;
    color: #1f6a37;
}

QPushButton#startButton:hover,
QPushButton#ledOnButton:hover {
    background: #dff0e4;
}

QPushButton#dangerButton,
QPushButton#ledOffButton {
    background: #fff1f0;
    border-color: #c98d89;
    color: #a12823;
}

QPushButton#dangerButton:hover,
QPushButton#ledOffButton:hover {
    background: #fbe2e0;
}

QPushButton#primaryButton:disabled,
QPushButton#startButton:disabled,
QPushButton#dangerButton:disabled,
QPushButton#ledOnButton:disabled,
QPushButton#ledOffButton:disabled {
    color: #969da4;
    background: #f2f3f4;
    border-color: #d5d8db;
}

QLabel#ledState {
    color: #5f6770;
    padding-left: 5px;
    font-weight: 600;
}

QLabel#ledState[ledState="on"] {
    color: #236b3d;
}

QLabel#statusTitle {
    color: #69717a;
    font-size: 8pt;
}

QLabel[systemStatus="true"] {
    color: #5f6770;
    font-size: 8.5pt;
    font-weight: 600;
}

QLabel[systemStatus="true"][status="ok"],
QLabel[systemStatus="true"][status="live"] {
    color: #236b3d;
}

QLabel[systemStatus="true"][status="warning"] {
    color: #9a5900;
}

QLabel[systemStatus="true"][status="error"] {
    color: #a12622;
}

QToolButton {
    min-height: 23px;
    padding: 1px 7px;
    border: 1px solid #b8bec4;
    border-radius: 2px;
    background: #f7f8f9;
    color: #46505a;
    font-weight: 500;
}

QToolButton:hover {
    border-color: #87949f;
    background: #eef1f3;
}

QToolButton:checked {
    background: #e6f0f7;
    border-color: #7098b2;
    color: #174f70;
}

QLineEdit,
QComboBox {
    min-height: 25px;
    padding: 1px 5px;
    background: #ffffff;
    border: 1px solid #aeb5bc;
    border-radius: 2px;
    color: #20252b;
    selection-background-color: #b9d6e8;
}

QComboBox {
    padding-right: 22px;
}

QLineEdit:focus,
QComboBox:focus {
    border-color: #5d8fac;
}

QLineEdit:disabled,
QComboBox:disabled {
    color: #8c949b;
    background: #f1f2f3;
    border-color: #d3d7da;
}

QCheckBox {
    spacing: 6px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
}

QTabWidget::pane {
    border: 1px solid #c9ced3;
    background: #ffffff;
}

QTabBar::tab {
    background: #eceff1;
    color: #4f5861;
    border: 1px solid #c9ced3;
    border-bottom: none;
    padding: 5px 10px;
    margin-right: 1px;
}

QTabBar::tab:selected {
    background: #ffffff;
    color: #20252b;
}

QTextBrowser,
QPlainTextEdit,
QTextEdit {
    background: #ffffff;
    border: 1px solid #c9ced3;
    border-radius: 2px;
    color: #252a30;
    selection-background-color: #c7ddeb;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 8.5pt;
}

QTableWidget,
QTreeWidget {
    background: #ffffff;
    alternate-background-color: #f7f8f9;
    border: 1px solid #c9ced3;
    color: #252a30;
    selection-background-color: #dcebf5;
    selection-color: #20252b;
    gridline-color: #e3e6e8;
    font-size: 8.5pt;
}

QTableWidget#operatorLog::item,
QTreeWidget#developerTree::item {
    min-height: 20px;
    padding: 1px 4px;
}

QHeaderView::section {
    background: #eef0f2;
    color: #4c555e;
    border: none;
    border-right: 1px solid #d5d9dd;
    border-bottom: 1px solid #c9ced3;
    padding: 3px 5px;
    font-weight: 600;
}

QPlainTextEdit#logDetail,
QPlainTextEdit#rawSnapshot {
    background: #fbfbfc;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: #eef0f2;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #b8bec4;
    border-radius: 3px;
    min-height: 25px;
}

QScrollBar::handle:vertical:hover {
    background: #969fa7;
}

QSplitter::handle {
    background: #d5d9dd;
}

QSplitter::handle:horizontal {
    width: 4px;
}

QSplitter::handle:vertical {
    height: 4px;
}
"""


def refresh_style(widget: QWidget) -> None:
    """Re-evaluate Qt stylesheet selectors after a dynamic property change."""

    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_dynamic_property(
    widget: QWidget,
    name: str,
    value: object,
) -> None:
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    refresh_style(widget)
