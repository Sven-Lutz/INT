from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

# ---------- Small UI model ----------


@dataclass(frozen=True)
class _StepItem:
    key: str
    label: str


# ---------- Right panel ----------


class RightFrame(QFrame):
    """
    Right-side status + timeline + monitor + metrics panel.

    Design goals:
    - minimal branching in UI updates
    - no repeated CSS string building at runtime
    - robust to unknown steps
    - QR rendering isolated + cached per URL
    """

    # Prebuilt styles (avoid re-allocating strings repeatedly)
    _CSS_PENDING = (
        "QLabel { background: #f2f2f2; border: 1px solid #d9d9d9; "
        "border-radius: 8px; padding: 4px 8px; color: #333; }"
    )
    _CSS_ACTIVE = (
        "QLabel { background: #e8f0ff; border: 1px solid #7aa7ff; "
        "border-radius: 8px; padding: 4px 8px; color: #153e8a; font-weight: 600; }"
    )
    _CSS_DONE = (
        "QLabel { background: #e9f7ef; border: 1px solid #6fcf97; "
        "border-radius: 8px; padding: 4px 8px; color: #1b6b3a; }"
    )

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

        self._steps: List[_StepItem] = [
            _StepItem("BACKWASH_INITIAL", "Backwash 1"),
            _StepItem("FILLING", "Filling"),
            _StepItem("FILTRATION", "Filtration"),
            _StepItem("VENTING", "Venting"),
            _StepItem("BACKWASH_FINAL", "Backwash 2"),
            _StepItem("FINISHED", "Finished"),
        ]
        self._step_keys: Tuple[str, ...] = tuple(s.key for s in self._steps)
        self._step_index: Dict[str, int] = {k: i for i, k in enumerate(self._step_keys)}

        self._current_step: str = "IDLE"
        self._qr_last_url: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._build_timeline(root)
        self._build_status_card(root)
        self._build_monitor_card(root)
        self._build_metrics_card(root)

        root.addStretch(1)

        self.set_step("IDLE")

    # ---------------- Builders ----------------

    def _gb(self, title: str) -> QGroupBox:
        gb = QGroupBox(title)
        gb.setStyleSheet("QGroupBox { font-weight: 600; } QLabel { padding: 2px; }")
        return gb

    def _build_timeline(self, root: QVBoxLayout) -> None:
        gb = self._gb("Timeline")
        lay = QHBoxLayout(gb)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        self._step_widgets: Dict[str, QLabel] = {}

        for i, st in enumerate(self._steps):
            w = QLabel(st.label)
            w.setAlignment(Qt.AlignCenter)
            w.setMinimumHeight(28)
            w.setStyleSheet(self._CSS_PENDING)
            w.setToolTip(st.key)
            self._step_widgets[st.key] = w
            lay.addWidget(w, 1)

            if i < len(self._steps) - 1:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet("QLabel { color: #888; padding: 0 2px; }")
                lay.addWidget(arrow, 0)

        root.addWidget(gb)

    def _build_status_card(self, root: QVBoxLayout) -> None:
        gb = self._gb("Status")
        lay = QVBoxLayout(gb)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.lbl_step = QLabel("IDLE")
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        self.lbl_step.setFont(f)

        self.lbl_status = QLabel("Idle")
        self.lbl_status.setWordWrap(True)

        self.ok_banner = QLabel("Manual OK required")
        self.ok_banner.setVisible(False)
        self.ok_banner.setWordWrap(True)
        self.ok_banner.setStyleSheet(
            "QLabel { background: #fff3cd; border: 1px solid #ffeeba; padding: 8px; border-radius: 8px; }"
        )

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)

        lay.addWidget(self.lbl_step)
        lay.addWidget(self.ok_banner)
        lay.addWidget(self.lbl_status)
        lay.addWidget(self.progress)

        root.addWidget(gb)

    def _build_monitor_card(self, root: QVBoxLayout) -> None:
        gb = self._gb("Live Monitor (Phone)")
        lay = QVBoxLayout(gb)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.qr_label = QLabel("QR not set")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedSize(180, 180)
        self.qr_label.setStyleSheet(
            "QLabel { background: #fafafa; border: 1px solid #ddd; border-radius: 12px; }"
        )

        self.qr_hint = QLabel("Scan QR to open the live monitor.")
        self.qr_hint.setAlignment(Qt.AlignCenter)
        self.qr_hint.setWordWrap(True)

        self.qr_url = QLabel("")
        self.qr_url.setAlignment(Qt.AlignCenter)
        self.qr_url.setWordWrap(True)
        self.qr_url.setTextInteractionFlags(Qt.TextSelectableByMouse)

        lay.addWidget(self.qr_label, 0, Qt.AlignHCenter)
        lay.addWidget(self.qr_hint)
        lay.addWidget(self.qr_url)

        root.addWidget(gb)

    def _build_metrics_card(self, root: QVBoxLayout) -> None:
        gb = self._gb("Metrics")
        lay = QVBoxLayout(gb)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)

        mono = QFont()
        mono.setStyleHint(QFont.Monospace)

        self.lbl_loss = QLabel("Loss (Filtration+Venting): 0.000 mL")
        self.lbl_loss.setFont(mono)

        self.lbl_flow = QLabel("Flow: —")
        self.lbl_flow.setFont(mono)

        self.lbl_pressure = QLabel("Pressure ch1: —   ch2: —")
        self.lbl_pressure.setFont(mono)

        self.lbl_valves = QLabel("Valves: —")
        self.lbl_valves.setFont(mono)

        lay.addWidget(self.lbl_loss)
        lay.addWidget(self.lbl_flow)
        lay.addWidget(self.lbl_pressure)
        lay.addWidget(self.lbl_valves)

        root.addWidget(gb)

    # ---------------- Public API ----------------

    def set_step(self, step: str) -> None:
        # Accept arbitrary step strings; only highlight known ones.
        self._current_step = step
        self.lbl_step.setText(step)

        idx = self._step_index.get(step, -1)

        if idx < 0:
            # Unknown step: keep everything pending (neutral state)
            for key in self._step_keys:
                w = self._step_widgets.get(key)
                if w is not None:
                    w.setStyleSheet(self._CSS_PENDING)
            return

        for j, key in enumerate(self._step_keys):
            w = self._step_widgets.get(key)
            if w is None:
                continue
            if j < idx:
                w.setStyleSheet(self._CSS_DONE)
            elif j == idx:
                w.setStyleSheet(self._CSS_ACTIVE)
            else:
                w.setStyleSheet(self._CSS_PENDING)

    def set_status(self, status: str) -> None:
        self.lbl_status.setText(status)

        needs_ok = ("manual ok required" in status.lower()) or ("waiting for ok" in status.lower())
        self.ok_banner.setVisible(needs_ok)
        if needs_ok:
            self.ok_banner.setText(status)

    def set_loss(self, loss_ml: float) -> None:
        self.lbl_loss.setText(f"Loss (Filtration+Venting): {float(loss_ml):.3f} mL")

    def set_metrics(
        self,
        *,
        flow: Optional[float] = None,
        p1_set: Optional[float] = None,
        p1_meas: Optional[float] = None,
        p2_set: Optional[float] = None,
        p2_meas: Optional[float] = None,
        valve_state: Optional[str] = None,
    ) -> None:
        self.lbl_flow.setText("Flow: —" if flow is None else f"Flow: {float(flow):.3f}")

        def fmt_pair(sp: Optional[float], ms: Optional[float]) -> str:
            if sp is None and ms is None:
                return "—"
            a = "—" if sp is None else f"{float(sp):.2f}%"
            b = "—" if ms is None else f"{float(ms):.2f}%"
            return f"{a}/{b}"

        self.lbl_pressure.setText(
            f"Pressure ch1: {fmt_pair(p1_set, p1_meas)}   ch2: {fmt_pair(p2_set, p2_meas)}"
        )
        self.lbl_valves.setText(f"Valves: {valve_state or '—'}")

    def set_busy(self, busy: bool) -> None:
        self.progress.setVisible(bool(busy))

    def set_qr_url(self, url: str) -> None:
        url = str(url).strip()
        self.qr_url.setText(url)
        self.qr_label.setToolTip(url)
        self.qr_url.setToolTip(url)

        # Avoid regenerating QR repeatedly for the same URL
        if url and url == self._qr_last_url and self.qr_label.pixmap() is not None:
            return
        self._qr_last_url = url

        if not url:
            self.qr_label.setPixmap(QPixmap())
            self.qr_label.setText("QR not set")
            self.qr_hint.setText("Scan QR to open the live monitor.")
            return

        pm = self._make_qr_pixmap(url, self.qr_label.width(), self.qr_label.height())
        if pm is None:
            self.qr_label.setPixmap(QPixmap())
            self.qr_label.setText("Install: pip install qrcode pillow")
            self.qr_hint.setText("QR generation unavailable (missing dependencies).")
            return

        self.qr_label.setPixmap(pm)
        self.qr_hint.setText("Scan QR to open the live monitor.")

    # ---------------- QR helpers ----------------

    def _make_qr_pixmap(self, url: str, w: int, h: int) -> Optional[QPixmap]:
        """
        Returns a scaled QPixmap for the given URL or None if deps missing / QR generation fails.
        """
        try:
            import qrcode
            from PIL.ImageQt import ImageQt  # type: ignore

            img = qrcode.make(url)
            qimg = QImage(ImageQt(img))
            pm = QPixmap.fromImage(qimg).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return pm
        except Exception:
            return None
