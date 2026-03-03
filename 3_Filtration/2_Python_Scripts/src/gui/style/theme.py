from __future__ import annotations
import os
import tempfile
from typing import Any
from PySide6.QtWidgets import QApplication, QWidget
from .tokens import ThemeTokens, industrial_dark_v2, industrial_light

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r, g, b = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        return f"rgba({r}, {g}, {b}, {alpha})"
    return hex_color

def _get_svg_path(color_hex: str, is_up: bool) -> str:
    pts = "18 15 12 9 6 15" if is_up else "6 9 12 15 18 9"
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color_hex}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
<polyline points="{pts}"></polyline>
</svg>"""
    name = "up.svg" if is_up else "dn.svg"
    path = os.path.join(tempfile.gettempdir(), f"chonk_pro_{color_hex.replace('#', '')}_{name}")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    except Exception:
        pass
    return path.replace('\\', '/')

def build_qss(t: ThemeTokens) -> str:
    up_arrow = _get_svg_path(t.text1, True)
    dn_arrow = _get_svg_path(t.text1, False)
    up_arrow_hov = _get_svg_path(t.accent, True)
    dn_arrow_hov = _get_svg_path(t.accent, False)

    ac_alpha = _hex_to_rgba(t.accent, 0.15)
    good_alpha = _hex_to_rgba(t.good, 0.15)
    bd_light = _hex_to_rgba(t.text1, 0.1)

    return f"""
    QWidget {{ background: {t.bg0}; color: {t.text0}; font-size: {t.fs_section}px; font-family: "Segoe UI", -apple-system, sans-serif; }}
    QLabel {{ background: transparent; color: {t.text1}; font-size: {t.fs_label}px; }}

    QLabel[role="title"] {{ color: {t.text0}; font-weight: 700; font-size: {t.fs_title}px; }}
    QLabel[role="hint"] {{ color: {t.text2}; font-size: {t.fs_hint}px; }}
    QLabel[role="value"] {{ color: {t.text0}; font-weight: 600; font-size: {t.fs_value}px; font-family: 'Consolas', monospace; }}

    QWidget[surface="panel"] {{ background: {t.bg1}; border-bottom: 1px solid {t.border}; }}
    QWidget[surface="card"] {{ background: {t.bg2}; border: 1px solid {t.border}; border-radius: {t.r_md}px; border-top: 1px solid {bd_light}; }}
    QWidget[surface="input"] {{ background: {t.bg3}; border: 1px solid {t.border}; border-radius: {t.r_sm}px; }}

    QGroupBox {{ border: 1px solid {t.border}; border-radius: {t.r_md}px; margin-top: 20px; background: {t.bg1}; }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 14px; padding: 0 6px; color: {t.text1}; font-weight: 600; }}

    /* ---------- INPUTS ---------- */
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {t.bg3}; border: 1px solid {t.border}; border-radius: {t.r_sm}px;
        padding: 8px 12px; color: {t.text0}; font-family: 'Consolas', monospace; font-size: 13px; font-weight: bold;
        selection-background-color: {t.accent}; selection-color: #000000;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {{
        border: 1px solid {t.accent}; background: {t.bg0};
    }}

    QSpinBox, QDoubleSpinBox {{ padding-right: 32px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border; subcontrol-position: top right;
        width: 28px; background: transparent; border-left: 1px solid {t.border}; border-bottom: 1px solid {t.border};
        border-top-right-radius: {t.r_sm}px;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right;
        width: 28px; background: transparent; border-left: 1px solid {t.border};
        border-bottom-right-radius: {t.r_sm}px;
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up_arrow}"); width: 12px; height: 12px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{dn_arrow}"); width: 12px; height: 12px; }}

    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{ background: {ac_alpha}; image: url("{up_arrow_hov}"); }}
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {ac_alpha}; image: url("{dn_arrow_hov}"); }}

    QWidget:disabled, QLabel:disabled {{ color: {t.text2}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {t.text2}; background: rgba(0,0,0,0.2); border: 1px dashed {t.border}; }}

    /* ---------- BUTTONS ---------- */
    QPushButton, QToolButton {{
        background: {t.bg2}; border: 1px solid {t.border}; border-top: 1px solid {bd_light};
        border-radius: {t.r_sm}px; padding: 8px 16px; color: {t.text0}; font-weight: bold;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {t.bg1}; border: 1px solid {t.accent}; color: {t.accent}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {t.accent}; color: #000000; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t.text2}; border: 1px solid {t.bg0}; background: {t.bg0}; }}

    /* ---------- PHASE PILLS ---------- */
    QLabel[role="pill"] {{ font-size: 11px; font-weight: 900; padding: 4px 10px; border-radius: 4px; text-transform: uppercase; letter-spacing: 1px; }}

    QWidget[phaseState="idle"]    QLabel[role="pill"] {{ background: transparent; border: none; color: {t.text2}; }}
    QWidget[phaseState="next"]    QLabel[role="pill"] {{ background: {ac_alpha}; border: 1px solid {t.accent}; color: {t.accent}; }}
    QWidget[phaseState="active"]  QLabel[role="pill"] {{ background: {t.good}; border: 1px solid {t.good}; color: #000000; }}
    QWidget[phaseState="done"]    QLabel[role="pill"] {{ background: transparent; border: none; color: {t.accent}; }}
    QWidget[phaseState="blocked"] QLabel[role="pill"] {{ background: transparent; border: 1px solid {t.bad}; color: {t.bad}; }}

    /* ---------- SCROLLBARS ---------- */
    QScrollArea, QScrollArea > QWidget > QWidget {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 5px; min-height: 20px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.text1}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

    /* ---------- TABS ---------- */
    QTabWidget::pane {{ border-top: 1px solid {t.border}; background: transparent; }}
    QTabBar::tab {{ background: transparent; color: {t.text1}; padding: 10px 24px; font-weight: bold; font-size: 13px; border: none; border-bottom: 3px solid transparent; letter-spacing: 1px; }}
    QTabBar::tab:selected {{ color: {t.accent}; border-bottom: 3px solid {t.accent}; }}
    QTabBar::tab:hover:!selected {{ color: {t.text0}; border-bottom: 3px solid {t.border}; }}
    """

def _select_tokens(theme_key: str) -> ThemeTokens:
    return industrial_light() if str(theme_key or "dark").strip().lower() == "light" else industrial_dark_v2()

def apply_theme(app_or_widget: Any, theme_key: str = "dark") -> None:
    qss = build_qss(_select_tokens(theme_key))
    if isinstance(app_or_widget, QApplication) or isinstance(app_or_widget, QWidget):
        app_or_widget.setStyleSheet(qss)
        return
    app = QApplication.instance()
    if app: app.setStyleSheet(qss)