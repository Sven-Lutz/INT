from __future__ import annotations

from collections import deque
from typing import Optional

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _is_finite(x) -> bool:
    try:
        import math
        return math.isfinite(float(x))
    except Exception:
        return False


class TopFrame(QFrame):
    def __init__(self, config: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config = config or {}

        self.setProperty("surface", "panel")
        self.setFixedHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._monitor_url: str = ""
        self._spark_len = 300
        self._spark_y1 = deque([0.0] * self._spark_len, maxlen=self._spark_len)
        self._spark_x = list(range(-self._spark_len, 0))

        # Root: overlay grid (plot in back, HUD on top)
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- BACKGROUND LAYER: spark plot ---
        self.spark_plot = pg.PlotWidget(self)
        self.spark_plot.setFixedHeight(110)
        self.spark_plot.setBackground(None)
        self.spark_plot.getPlotItem().hideAxis("bottom")
        self.spark_plot.getPlotItem().hideAxis("left")
        self.spark_plot.setMouseEnabled(x=False, y=False)
        self.spark_plot.setMenuEnabled(False)
        self.spark_plot.showGrid(x=False, y=True, alpha=0.1)
        self.spark_plot.enableAutoRange(axis="y", enable=True)
        self.spark_plot.setYRange(0, 1000)

        grad = QLinearGradient(0, 0, 0, 1)
        grad.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
        grad.setColorAt(0.0, QColor(0, 229, 255, 60))  # cyan
        grad.setColorAt(1.0, QColor(0, 229, 255, 0))
        brush = QBrush(grad)

        pen = pg.mkPen(color="#00E5FF", width=2)
        self.spark_curve = self.spark_plot.plot(
            pen=pen, fillLevel=0, brush=brush, antialias=True
        )
        self.spark_head = self.spark_plot.plot(
            [], [], pen=None, symbol="o", symbolBrush="#00E5FF", symbolSize=6
        )

        # --- FOREGROUND LAYER: HUD ---
        hud_container = QWidget(self)
        hud_container.setAttribute(Qt.WA_TranslucentBackground, True)
        hud_container.setStyleSheet("background: transparent;")

        hud_lay = QHBoxLayout(hud_container)
        hud_lay.setContentsMargins(25, 0, 25, 0)
        hud_lay.setSpacing(40)

        # Brand block
        brand = QVBoxLayout()
        brand.setSpacing(2)

        self.lbl_title = QLabel("LITTLE CHONKER")
        self.lbl_title.setStyleSheet(
            "font-size: 16px; font-weight: 900; letter-spacing: 2px; color: #F8FAFC;"
        )

        net_row = QHBoxLayout()
        net_row.setSpacing(8)

        self.lbl_net_dot = QLabel("●")
        self.lbl_net_dot.setStyleSheet("color: #4B5563; font-size: 12px;")

        self.lbl_net_text = QLabel("OFFLINE")
        self.lbl_net_text.setStyleSheet(
            "font-size: 10px; font-weight: bold; color: #6B7280;"
        )

        self.btn_copy_net = QPushButton("COPY LINK")
        self.btn_copy_net.setCursor(Qt.PointingHandCursor)
        self.btn_copy_net.setStyleSheet(
            "font-size: 9px; font-weight: bold; padding: 2px 8px; border-radius: 4px;"
            "color: #00E5FF; border: 1px solid #00E5FF; background: transparent;"
        )
        self.btn_copy_net.clicked.connect(self._copy_monitor_url)
        self.btn_copy_net.hide()

        net_row.addWidget(self.lbl_net_dot)
        net_row.addWidget(self.lbl_net_text)
        net_row.addWidget(self.btn_copy_net)
        net_row.addStretch(1)

        brand.addWidget(self.lbl_title)
        brand.addLayout(net_row)

        hud_lay.addLayout(brand)
        hud_lay.addStretch(1)

        # Stats
        self.val_loss = self._hud_stat("LOSS", "mL", accent="#F8FAFC")
        self.val_target = self._hud_stat("TARGET", "mL", accent="#00E676")
        hud_lay.addLayout(self.val_loss)
        hud_lay.addLayout(self.val_target)
        hud_lay.addStretch(1)

        # System status box
        self.box_status = QFrame()
        self.box_status.setStyleSheet(
            "background: transparent; border: 1px solid #10B981; border-radius: 4px; padding: 6px 16px;"
        )
        self.lbl_status = QLabel("SYSTEM OK")
        self.lbl_status.setStyleSheet(
            "color: #10B981; font-weight: bold; font-size: 11px; letter-spacing: 1.5px;"
        )
        QHBoxLayout(self.box_status).addWidget(self.lbl_status)
        hud_lay.addWidget(self.box_status, 0, Qt.AlignCenter)
        hud_lay.addStretch(1)

        # KPIs
        self.val_p1 = self._hud_stat("P1 MAIN", "mbar", large=True)
        self.val_p2 = self._hud_stat("P2 BACK", "mbar", large=True)
        self.val_flow = self._hud_stat("FLOW", "mL/min", large=False)
        self.val_valve = self._hud_stat("VALVES", "", large=False)

        hud_lay.addLayout(self.val_p1)
        hud_lay.addLayout(self.val_p2)
        hud_lay.addLayout(self.val_flow)
        hud_lay.addLayout(self.val_valve)

        # Add background + overlay to same cell
        root.addWidget(self.spark_plot, 0, 0)
        root.addWidget(hud_container, 0, 0)
        root.setRowStretch(0, 1)
        root.setColumnStretch(0, 1)

    def _hud_stat(
        self, name: str, unit: str, large: bool = False, accent: str = "#F8FAFC"
    ) -> QVBoxLayout:
        lay = QVBoxLayout()
        lay.setSpacing(0)

        n = QLabel(name)
        n.setStyleSheet(
            "color: #94A3B8; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )

        v = QLabel("—")
        v_size = "32px" if large else "22px"
        v.setStyleSheet(
            f"color: {accent}; font-size: {v_size}; font-family: 'Consolas', monospace; font-weight: bold;"
        )

        lay.addWidget(n)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(v)

        if unit:
            u = QLabel(unit)
            u.setStyleSheet(
                "color: #6B7280; font-size: 10px; font-weight: bold; padding-top: 6px;"
            )
            row.addWidget(u)

        lay.addLayout(row)

        # store value label handle
        lay._v = v  # type: ignore[attr-defined]
        return lay

    # ---------------------------
    # Monitor URL / Copy handling
    # ---------------------------
    def set_monitor_url(self, url: str) -> None:
        url = (url or "").strip()
        self._monitor_url = url

        online = bool(url)
        if online:
            self.lbl_net_dot.setStyleSheet("color: #10B981; font-size: 12px;")
            self.lbl_net_text.setText("ONLINE")
            self.lbl_net_text.setStyleSheet(
                "font-size: 10px; font-weight: bold; color: #10B981;"
            )
            self.btn_copy_net.show()
            self.btn_copy_net.setToolTip(url)
        else:
            self.lbl_net_dot.setStyleSheet("color: #4B5563; font-size: 12px;")
            self.lbl_net_text.setText("OFFLINE")
            self.lbl_net_text.setStyleSheet(
                "font-size: 10px; font-weight: bold; color: #6B7280;"
            )
            self.btn_copy_net.hide()
            self.btn_copy_net.setToolTip("")

    def _copy_monitor_url(self) -> None:
        url = (self._monitor_url or "").strip()
        if not url:
            # defensive: shouldn't happen because button hidden, but safe anyway
            QTimer.singleShot(0, lambda: QApplication.beep())
            return

        QApplication.clipboard().setText(url)

        # UI feedback: text swap + tooltip
        old = self.btn_copy_net.text()
        self.btn_copy_net.setText("COPIED ✓")
        self.btn_copy_net.setStyleSheet(
            "font-size: 9px; font-weight: bold; padding: 2px 8px; border-radius: 4px;"
            "color: #10B981; border: 1px solid #10B981; background: transparent;"
        )
        self.btn_copy_net.setToolTip(f"Copied:\n{url}")

        QTimer.singleShot(900, lambda: self._restore_copy_button(old))

    def _restore_copy_button(self, old_text: str) -> None:
        self.btn_copy_net.setText(old_text)
        self.btn_copy_net.setStyleSheet(
            "font-size: 9px; font-weight: bold; padding: 2px 8px; border-radius: 4px;"
            "color: #00E5FF; border: 1px solid #00E5FF; background: transparent;"
        )
        if self._monitor_url:
            self.btn_copy_net.setToolTip(self._monitor_url)

    # ---------------------------
    # Existing API hooks
    # ---------------------------
    def set_results(self, loss_ml: float, target_ml: float) -> None:
        self.val_loss._v.setText(f"{loss_ml:.3f}")   # type: ignore[attr-defined]
        self.val_target._v.setText(f"{target_ml:.3f}")  # type: ignore[attr-defined]

    def set_health_snapshot(self, snap) -> None:
        # snap.health expected enum-like with .value, matches your existing integration
        self.lbl_status.setText(f"SYSTEM {snap.health.value}")

        color = "#10B981"
        # keep your names; you can map more states here if needed
        if getattr(snap, "health", None) is not None:
            if str(snap.health).endswith("WARNING"):
                color = "#F59E0B"
            if str(snap.health).endswith("ALARM") or str(snap.health).endswith("ERROR"):
                color = "#EF4444"

        self.box_status.setStyleSheet(
            f"background: transparent; border: 1px solid {color}; border-radius: 4px; padding: 4px 16px;"
        )
        self.lbl_status.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 12px; letter-spacing: 1.5px;"
        )

    def set_hold_state(self, *, active: bool, allowed: bool) -> None:
        # Placeholder (kept as in your file)
        pass

    def set_trend(self, *, up_mode: str, dn_mode: str, up_text: str = "", dn_text: str = "") -> None:
        # Placeholder (kept as in your file)
        pass

    def set_kpis(self, *, p1_mbar=None, p2_mbar=None, flow=None, valves=None) -> None:
        self.val_p1._v.setText(f"{p1_mbar:.0f}" if p1_mbar is not None else "—")  # type: ignore[attr-defined]
        self.val_p2._v.setText(f"{p2_mbar:.0f}" if p2_mbar is not None else "—")  # type: ignore[attr-defined]
        self.val_flow._v.setText(f"{flow:.3f}" if flow is not None else "—")      # type: ignore[attr-defined]

        v_text = str(valves).strip().upper() if valves else "—"
        self.val_valve._v.setText(v_text)  # type: ignore[attr-defined]

        ff = "font-family: 'Consolas', monospace; font-weight: bold;"
        if v_text in ("FILTRATION", "FILLING"):
            self.val_valve._v.setStyleSheet(f"color: #10B981; font-size: 20px; {ff}")  # type: ignore[attr-defined]
        elif v_text in ("VENTING", "VENT"):
            self.val_valve._v.setStyleSheet(f"color: #94A3B8; font-size: 20px; {ff}")  # type: ignore[attr-defined]
        elif "BACKWASH" in v_text:
            self.val_valve._v.setStyleSheet(f"color: #8B5CF6; font-size: 20px; {ff}")  # type: ignore[attr-defined]
        else:
            self.val_valve._v.setStyleSheet(f"color: #F8FAFC; font-size: 20px; {ff}")  # type: ignore[attr-defined]

        if p1_mbar is not None and _is_finite(p1_mbar):
            v_val = float(p1_mbar)
            self._spark_y1.append(v_val)
            self.spark_curve.setData(self._spark_x, list(self._spark_y1))
            self.spark_head.setData([self._spark_x[-1]], [v_val])