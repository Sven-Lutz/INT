from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional, Dict
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
    QTextEdit
)
from src.gui.style.phase_map import PHASE_ORDER, normalize_step, compute_phase_states


class RightFrame(QFrame):
    start_clicked = Signal()
    ok_clicked = Signal()
    stop_clicked = Signal()
    manual_vent_clicked = Signal()

    def __init__(self, config: Optional[dict] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("surface", "panel")

        self._current_step = "IDLE"
        self._running = False
        self._step_elapsed_s: Optional[float] = None
        self._step_total_s: Optional[float] = None
        self._eta_s: Optional[float] = None

        self._loss_ml = 0.0
        self._hold_removed_ml = 0.0
        self._base_remove_ml = 0.0

        self.pulse_timer = QTimer(self)
        self.pulse_timer.timeout.connect(self._pulse_active_phase)
        self._pulse_state = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.content = QWidget()

        root = QVBoxLayout(self.content)
        root.setContentsMargins(15, 10, 15, 15)
        root.setSpacing(15)

        self._build_phase_overview(root)
        self._build_run_state_card(root)
        self._build_output_preview_card(root)
        self._build_terminal_card(root)

        root.addStretch(1)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)

        footer = QWidget()
        footer.setProperty("surface", "panel")
        footer_lay = QVBoxLayout(footer)
        footer_lay.setContentsMargins(15, 0, 15, 15)
        self._build_run_controls(footer_lay)
        outer.addWidget(footer, 0)

        self.reset_state()

    def _card(self, title: str) -> QFrame:
        c = QFrame()
        c.setStyleSheet("background: #111827; border-radius: 8px; border: 1px solid #1E293B;")
        lay = QVBoxLayout(c)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(12)

        t = QLabel(title)
        t.setStyleSheet(
            "font-family: 'Consolas', monospace; font-size: 11px; font-weight: bold; color: #E2E8F0; letter-spacing: 1.5px; border: none;")
        lay.addWidget(t)
        return c

    def _build_phase_overview(self, root: QVBoxLayout) -> None:
        card = self._card("SEQUENCE PROGRESS")
        lay = card.layout()
        grid = QGridLayout();
        grid.setHorizontalSpacing(10);
        grid.setVerticalSpacing(10)
        self._phase_boxes = {}

        display_phases = [p for p in PHASE_ORDER if "HOLD" not in p]

        for i, key in enumerate(display_phases):
            box = QFrame()
            box.setStyleSheet("background: #050914; border-radius: 6px; border: 1px solid #1A202C; padding: 6px;")
            bl = QVBoxLayout(box);
            bl.setContentsMargins(8, 8, 8, 8);
            bl.setSpacing(6)

            name = QLabel(key.replace("BACKWASH_INITIAL", "Backwash 1").replace("BACKWASH_FINAL", "Backwash 2").title())
            name.setStyleSheet(
                "font-family: 'Consolas', monospace; font-size: 11px; font-weight: bold; color: #A0AEC0; border: none;")

            pill = QLabel("IDLE")
            pill.setAlignment(Qt.AlignCenter)
            pill.setStyleSheet(
                "background: transparent; color: #4A5568; font-size: 10px; font-weight: bold; font-family: 'Consolas', monospace; border: none;")

            bl.addWidget(name);
            bl.addWidget(pill, 0, Qt.AlignLeft)
            grid.addWidget(box, i // 3, i % 3)
            self._phase_boxes[key] = {'root': box, 'pill': pill}

        lay.addLayout(grid);
        root.addWidget(card)

    def _pulse_active_phase(self):
        self._pulse_state = not self._pulse_state
        for key, v in self._phase_boxes.items():
            if v['pill'].text() == "ACTIVE":
                if self._pulse_state:
                    # CHROMA GLOW
                    v['root'].setStyleSheet(
                        "background: rgba(139, 92, 246, 0.2); border-radius: 6px; border: 1px solid #8B5CF6; padding: 6px;")
                else:
                    v['root'].setStyleSheet(
                        "background: rgba(139, 92, 246, 0.05); border-radius: 6px; border: 1px solid #7C3AED; padding: 6px;")

    def _build_run_state_card(self, root: QVBoxLayout) -> None:
        card = self._card("CURRENT STATUS")
        lay = card.layout()

        self.lbl_step = QLabel("IDLE")
        self.lbl_step.setStyleSheet(
            "font-family: 'Consolas', monospace; font-size: 22px; font-weight: bold; color: #F8FAFC; border: none;")

        self.ok_box = QFrame()
        self.ok_box.setStyleSheet(
            "background: #111827; border: 1px solid #F59E0B; border-left: 4px solid #F59E0B; border-radius: 4px; padding: 8px;")
        self.ok_box.setVisible(False)
        self.ok_banner = QLabel("")
        self.ok_banner.setStyleSheet(
            "color: #F59E0B; font-size: 12px; font-family: 'Consolas', monospace; font-weight: bold; border: none;")
        self.ok_banner.setWordWrap(True)
        QHBoxLayout(self.ok_box).addWidget(self.ok_banner)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        # 🚀 CHROMA GRADIENT: Pink -> Purple -> Cyan 🚀
        self.progress.setStyleSheet(
            "QProgressBar { background: #050914; border: none; border-radius: 4px; } QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EC4899, stop:0.5 #8B5CF6, stop:1 #00E5FF); border-radius: 4px; }")

        self.lbl_eta = QLabel("—")
        self.lbl_eta.setStyleSheet(
            "font-family: 'Consolas', monospace; font-weight: bold; color: #A0AEC0; font-size: 12px; border: none;")

        lay.addWidget(self.lbl_step);
        lay.addWidget(self.ok_box);
        lay.addWidget(self.progress);
        lay.addWidget(self.lbl_eta)
        root.addWidget(card)

    def _build_output_preview_card(self, root: QVBoxLayout) -> None:
        card = self._card("TELEMETRY MATH")
        lay = card.layout()
        host = QWidget()
        grid = QGridLayout(host);
        grid.setContentsMargins(0, 0, 0, 0);
        grid.setVerticalSpacing(8)

        font_style = "font-family: 'Consolas', monospace; font-size: 14px; font-weight: bold; border: none;"

        self.val_loss = QLabel("0.000 mL");
        self.val_loss.setStyleSheet(f"{font_style} color: #F8FAFC;")
        self.val_hold_removed = QLabel("0.000 mL");
        self.val_hold_removed.setStyleSheet(f"{font_style} color: #F8FAFC;")
        self.val_target_remove = QLabel("0.000 mL");
        self.val_target_remove.setStyleSheet(f"{font_style} color: #00E5FF; font-size: 18px;")

        l1 = QLabel("Loss (Filt+Vent)");
        l1.setStyleSheet(
            "font-family: 'Consolas', monospace; color: #A0AEC0; font-size: 11px; font-weight: bold; border: none;")
        l2 = QLabel("Manual HOLD");
        l2.setStyleSheet(
            "font-family: 'Consolas', monospace; color: #A0AEC0; font-size: 11px; font-weight: bold; border: none;")
        l3 = QLabel("Target Remove");
        l3.setStyleSheet(
            "font-family: 'Consolas', monospace; color: #F8FAFC; font-size: 12px; font-weight: bold; border: none;")

        grid.addWidget(l1, 0, 0);
        grid.addWidget(self.val_loss, 0, 1)
        grid.addWidget(l2, 1, 0);
        grid.addWidget(self.val_hold_removed, 1, 1)
        grid.addWidget(l3, 2, 0);
        grid.addWidget(self.val_target_remove, 2, 1)
        lay.addWidget(host);
        root.addWidget(card)

    def _build_terminal_card(self, root: QVBoxLayout) -> None:
        card = self._card("SYSTEM CONSOLE")
        lay = card.layout()
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFixedHeight(180)
        self.console.setStyleSheet(
            "background-color: #050914; color: #00E5FF; font-family: 'Consolas', monospace; font-size: 12px; border: 1px solid #1A202C; border-radius: 4px; padding: 10px;")
        lay.addWidget(self.console);
        root.addWidget(card)

    def _build_run_controls(self, lay: QVBoxLayout) -> None:
        row = QHBoxLayout();
        row.setContentsMargins(0, 10, 0, 0);
        row.setSpacing(12)

        def _btn(text, color):
            b = QPushButton(text)
            b.setStyleSheet(f"""
                QPushButton {{ 
                    font-family: 'Consolas', monospace; font-size: 13px; font-weight: bold; letter-spacing: 1px; padding: 16px; 
                    background-color: #111827; 
                    border: 1px solid #1F2937; border-bottom: 3px solid {color}; 
                    color: #F8FAFC; border-radius: 4px; 
                }}
                QPushButton:hover {{ background-color: #1E293B; border: 1px solid {color}; }}
                QPushButton:disabled {{ border: 1px solid #111827; color: #4A5568; border-bottom: 3px solid #111827; background-color: #050914; }}
            """)
            return b

        self.btn_start = _btn("START RUN", "#8B5CF6")  # Purple
        self.btn_ok = _btn("CONFIRM STEP", "#00E5FF")  # Cyan
        self.btn_vent = _btn("VENT", "#A0AEC0")  # Silver
        self.btn_stop = _btn("ABORT RUN", "#FF1744")  # Red

        self.btn_ok.setEnabled(False)
        self.btn_stop.setEnabled(False)

        self.btn_start.clicked.connect(self.start_clicked.emit)
        self.btn_ok.clicked.connect(self.ok_clicked.emit)
        self.btn_vent.clicked.connect(self.manual_vent_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)

        row.addWidget(self.btn_start, 2)
        row.addWidget(self.btn_ok, 2)
        row.addWidget(self.btn_vent, 1)
        row.addWidget(self.btn_stop, 2)
        lay.addLayout(row)

    def append_log(self, msg: str, color: str = "#8B5CF6") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.console.append(
            f'<span style="color: #4A5568;">[{ts}]</span> <span style="color: {color}; font-weight: bold;">{msg}</span>')
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def reset_state(self) -> None:
        self.set_loss_ml(0.0)
        self.set_hold_removed_ml(0.0)
        self.set_step("IDLE")
        self.set_status("Idle")
        self.progress.setValue(0)
        self.lbl_eta.setText("—")
        self.set_running(False)
        self.ok_box.setVisible(False)
        self.pulse_timer.stop()

        for k, v in self._phase_boxes.items():
            v['root'].setStyleSheet("background: #050914; border-radius: 4px; border: 1px solid #1A202C; padding: 6px;")
            v['pill'].setStyleSheet(
                "background: transparent; color: #4A5568; font-size: 10px; font-weight: bold; border: none;")
            v['pill'].setText("IDLE")

    @Slot(float)
    def set_loss_ml(self, v: float):
        self._loss_ml = float(v); self.val_loss.setText(f"{self._loss_ml:.3f} mL"); self._calc()

    @Slot(float)
    def set_hold_removed_ml(self, v: float):
        self._hold_removed_ml = float(v); self.val_hold_removed.setText(f"{self._hold_removed_ml:.3f} mL"); self._calc()

    def set_base_remove_ml(self, v: float):
        self._base_remove_ml = float(v); self._calc()

    def _calc(self):
        self.val_target_remove.setText(
            f"{max(0.0, self._base_remove_ml + self._loss_ml + self._hold_removed_ml):.3f} mL")

    def set_running(self, running: bool):
        self._running = running
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        if not running: self.btn_ok.setEnabled(False)

    def enable_ok(self, e: bool):
        self.btn_ok.setEnabled(e)

    def set_status(self, s: str):
        if s and "OK required" not in s: self.append_log(f"SYS: {s}", "#A0AEC0")

    def set_ok_banner(self, *, step: str = "", reason: str = "", show: bool = True) -> None:
        if not show:
            self.ok_box.setVisible(False)
            return
        st = str(step or "").strip();
        rs = str(reason or "").strip()
        self.ok_banner.setText(f"> {st}: {rs}" if (st and rs) else (f"> {rs}" if rs else "> MANUAL OK REQUIRED"))
        self.ok_box.setVisible(True)

    def set_manual_state(self, **kwargs):
        pass

    def set_step(self, step: str) -> None:
        self._current_step = normalize_step(step) or "IDLE"
        self.lbl_step.setText(self._current_step)

        if self._current_step not in ("IDLE", "FINISHED"):
            self.append_log(f"PHASE: {self._current_step}", "#00E5FF")

        if self._current_step in ("FINISHED", "DONE"):
            states = {p: "done" for p in PHASE_ORDER}
            self.pulse_timer.stop()
        elif self._current_step in PHASE_ORDER:
            states = compute_phase_states(self._current_step, set(PHASE_ORDER[:PHASE_ORDER.index(self._current_step)]),
                                          set())
            self.pulse_timer.start(500)
        else:
            states = compute_phase_states("", set(), set())
            self.pulse_timer.stop()

        for k, v in self._phase_boxes.items():
            st = states.get(k, 'idle')
            if st == 'active':
                v['root'].setStyleSheet(
                    "background: rgba(139, 92, 246, 0.2); border-radius: 6px; border: 1px solid #8B5CF6; padding: 6px;")
                v['pill'].setStyleSheet(
                    "background: #8B5CF6; color: #FFFFFF; font-size: 11px; font-weight: bold; border-radius: 3px; padding: 2px 8px;")
            elif st == 'done':
                v['root'].setStyleSheet(
                    "background: #09090C; border-radius: 4px; border: 1px solid #1F2937; padding: 6px;")
                v['pill'].setStyleSheet(
                    "background: transparent; color: #00E5FF; font-size: 11px; font-weight: bold; border: none;")
            else:
                v['root'].setStyleSheet(
                    "background: #050914; border-radius: 4px; border: 1px solid #1F2937; padding: 6px;")
                v['pill'].setStyleSheet(
                    "background: transparent; color: #4A5568; font-size: 10px; font-weight: bold; border: none;")
            v['pill'].setText(st.upper())

    def set_step_progress(self, *, step_elapsed_s=None, step_total_s=None, eta_s=None, text="") -> None:
        if text: self.lbl_eta.setText(str(text))
        if self._current_step == "BACKWASH_HOLD":
            self.progress.setValue(0);
            self.lbl_eta.setText("HOLD active...");
            return

        if step_elapsed_s and step_total_s and step_total_s > 0:
            pct = int((step_elapsed_s / step_total_s) * 100)
            self.progress.setValue(pct)
            calc_eta = eta_s if eta_s is not None else max(0.0, step_total_s - step_elapsed_s)
            self.lbl_eta.setText(f"ETA: {calc_eta:.1f} s")
        else:
            self.progress.setValue(0)
            if not text: self.lbl_eta.setText("—")