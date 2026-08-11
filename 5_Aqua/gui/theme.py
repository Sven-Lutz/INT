from __future__ import annotations

from PySide6.QtWidgets import QWidget


AQUA_STYLESHEET = """
QWidget {
    background: #0b1118;
    color: #dce7f2;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QMainWindow {
    background: #080d13;
}

QLabel,
QCheckBox {
    background: transparent;
}

QFrame#headerFrame {
    background: #0f1722;
    border: 1px solid #203044;
    border-radius: 12px;
}

QLabel#appTitle {
    color: #f4f8fb;
    font-size: 20pt;
    font-weight: 700;
}

QLabel#appSubtitle {
    color: #7f93a8;
    font-size: 9pt;
}

QLabel[statusChip="true"] {
    background: #162230;
    border: 1px solid #30445c;
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 9pt;
    font-weight: 700;
}

QLabel[status="ready"],
QLabel[status="live"],
QLabel[status="ok"] {
    color: #72e0a1;
    border-color: #2b7751;
    background: #10261d;
}

QLabel[status="running"] {
    color: #65d9ff;
    border-color: #25708a;
    background: #0e2630;
}

QLabel[status="warning"],
QLabel[status="stale"] {
    color: #ffc96b;
    border-color: #7a5b26;
    background: #2b2110;
}

QLabel[status="error"],
QLabel[status="fault"] {
    color: #ff7d8d;
    border-color: #7d3240;
    background: #2b1318;
}

QLabel[status="muted"],
QLabel[status="disconnected"] {
    color: #8da0b2;
    border-color: #354352;
    background: #151d26;
}

QGroupBox {
    background: #0f1722;
    border: 1px solid #203044;
    border-radius: 10px;
    margin-top: 13px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: #93a8bb;
    background: #0f1722;
    font-size: 9pt;
}

QFrame#telemetryCard {
    background: #111c28;
    border: 1px solid #22364a;
    border-radius: 9px;
}

QFrame#telemetryCard[metricClickable="true"]:hover {
    background: #152434;
    border-color: #3d7993;
}

QLabel#telemetryTitle {
    color: #7f93a8;
    font-size: 8pt;
    font-weight: 600;
}

QLabel#telemetryValue {
    color: #edf5fb;
    font-size: 16pt;
    font-weight: 700;
}

QLabel#telemetryDetail {
    color: #7690a5;
    font-size: 8pt;
}

QFrame#telemetryCard[severity="warning"] {
    border-color: #7b5d2d;
}

QFrame#telemetryCard[severity="error"] {
    border-color: #7d3240;
    background: #21151b;
}

QFrame#telemetryCard[severity="ok"] {
    border-color: #2a6447;
}

QPushButton {
    min-height: 30px;
    padding: 4px 12px;
    border: 1px solid #30445b;
    border-radius: 7px;
    background: #172331;
    color: #dce7f2;
    font-weight: 600;
}

QPushButton:hover {
    background: #1d3041;
    border-color: #48657e;
}

QPushButton:pressed {
    background: #10202e;
}

QPushButton:disabled {
    color: #627486;
    background: #101821;
    border-color: #22303d;
}

QPushButton#primaryButton {
    background: #0f647f;
    border-color: #2f91ad;
    color: #f7fcff;
}

QPushButton#primaryButton:hover {
    background: #147793;
}

QPushButton#dangerButton {
    background: #612734;
    border-color: #9b4150;
    color: #ffe9ed;
}

QPushButton#dangerButton:hover {
    background: #773040;
}

QToolButton {
    min-height: 26px;
    padding: 3px 10px;
    border: 1px solid #2b3f53;
    border-radius: 7px;
    background: #121d28;
    color: #91a5b7;
    font-weight: 600;
}

QToolButton:hover {
    border-color: #456b83;
    color: #dce7f2;
}

QToolButton:checked {
    background: #15384a;
    border-color: #2e87a6;
    color: #8ce3ff;
}

QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {
    min-height: 28px;
    padding: 2px 7px;
    background: #0c151f;
    border: 1px solid #2a3d50;
    border-radius: 6px;
    selection-background-color: #1c6f8d;
}

QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border-color: #3b9aba;
}

QCheckBox {
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
}

QTabWidget::pane {
    border: 1px solid #203044;
    background: #0e1620;
    border-radius: 8px;
}

QTabBar::tab {
    background: #111a24;
    color: #8094a7;
    border: 1px solid #203044;
    padding: 7px 12px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background: #162635;
    color: #dce7f2;
    border-bottom-color: #2f91ad;
}

QTextBrowser,
QPlainTextEdit,
QTextEdit {
    background: #091018;
    border: 1px solid #1e2e3e;
    border-radius: 6px;
    color: #cbd8e3;
    selection-background-color: #205e78;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9pt;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: #0b121a;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #2b3c4d;
    border-radius: 5px;
    min-height: 28px;
}

QScrollBar::handle:vertical:hover {
    background: #3b5368;
}

QSplitter::handle {
    background: #111b25;
}

QSplitter::handle:horizontal {
    width: 5px;
}

QSplitter::handle:vertical {
    height: 5px;
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
