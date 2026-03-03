# src/gui/app.py
from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from src.utils.config_manager import ConfigManager
from src.utils.path_utils import ensure_dir, project_root, resolve_under

from .data.logger import setup_gui_logging
from .main_window import MainWindow
from .style.theme import apply_theme  # <<< SSOT theme entrypoint

logger = logging.getLogger(__name__)


# ---------------- Paths / Logging ----------------

def _compute_log_dir() -> Path:
    """
    Prefer repo-root/logs (shared with backend logs).
    Fallback: src/gui/logs.
    """
    try:
        root = project_root(__file__)  # anchored on this file
        log_dir = Path(resolve_under(root, "logs"))
    except Exception:
        log_dir = Path(__file__).resolve().parent / "logs"

    ensure_dir(str(log_dir))
    return log_dir


def _configure_env_for_qt() -> None:
    """
    Make Qt behave nicely on Windows lab PCs.
    """
    # Ensure consistent dark mode behavior (Windows tends to pick odd palette in some setups).
    # This does NOT force a theme by itself, but helps avoid platform-dependent surprises.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")


def _configure_qt_highdpi() -> None:
    """
    Qt6 handles HiDPI well by default, but explicit rounding policy helps on mixed-DPI setups.
    """
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass


def _install_exception_hook() -> None:
    """
    Make uncaught exceptions visible (and logged) instead of silently dying.
    """

    def excepthook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        logger.critical("Uncaught exception:\n%s", msg)

        # Avoid re-entrancy issues: show dialog on next tick if QApplication exists
        app = QApplication.instance()

        if app is not None:

            def _show():
                try:
                    # show the full traceback (critical for debugging in the lab)
                    QMessageBox.critical(None, "Fatal error", msg)
                except Exception:
                    pass

            QTimer.singleShot(0, _show)

        # Keep default behavior (exit with traceback)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook


# ---------------- App helpers ----------------

def _maybe_set_app_icon(app: QApplication) -> None:
    """
    Optional: set an app icon if a common path exists.
    Never fail if missing.
    """
    try:
        root = project_root(__file__)
        for rel in (
            "assets/icon.png",
            "assets/icon.ico",
            "src/gui/assets/icon.png",
            "src/gui/assets/icon.ico",
        ):
            p = Path(resolve_under(root, rel))
            if p.exists():
                app.setWindowIcon(QIcon(str(p)))
                return
    except Exception:
        return


def _sanity_check_monitor_port(cfg: dict) -> None:
    """
    Avoid the common 'QR not working' symptom caused by binding to localhost or a blocked interface.
    This does NOT enforce settings; it just warns in logs.
    """
    host = str(cfg.get("monitor_host", "0.0.0.0")).strip() or "0.0.0.0"
    port = int(cfg.get("monitor_port", 8765))

    if host in ("127.0.0.1", "localhost"):
        logger.warning(
            "monitor_host=%s will not be reachable from phone. Use 0.0.0.0 for LAN access.",
            host,
        )
    if port <= 0 or port > 65535:
        logger.warning("monitor_port=%s is invalid; monitor may fail to start.", port)


def _load_general_config_best_effort() -> dict:
    """
    Load config early to fail fast and to validate monitor settings.
    Never crashes the GUI.
    """
    try:
        cfg = ConfigManager().load_config("general")
        if isinstance(cfg, dict):
            return cfg
        logger.warning("ConfigManager.load_config('general') returned non-dict: %r", type(cfg))
        return {}
    except Exception:
        logger.exception("Failed to load general config at startup (non-fatal).")
        return {}


def _get_ui_theme_key(cfg: dict) -> str:
    """
    Resolve UI theme from config (single source of truth).
    Supports:
      ui:
        theme: dark|light
    Falls back to 'dark'.
    """
    try:
        ui = cfg.get("ui", {})
        if isinstance(ui, dict):
            k = str(ui.get("theme", "dark")).strip().lower()
        else:
            k = "dark"
        return "light" if k == "light" else "dark"
    except Exception:
        return "dark"


def _single_instance_guard(app_key: str = "LittleChonker") -> Optional[QApplication]:
    """
    Minimal single-instance protection using Qt's application name + PID lockfile.
    Works without additional deps. If lock cannot be acquired -> shows dialog and exits.

    NOTE: This avoids 2 GUIs opening the same COM ports (common lab failure mode).
    """
    try:
        # Use a per-user temp dir. Windows: %TEMP%, macOS/Linux: /tmp-like.
        base = Path(os.environ.get("TEMP", "") or os.environ.get("TMPDIR", "") or "/tmp")
        lock = base / f"{app_key}.lock"

        # Best-effort lock: create exclusively
        # If it exists and the PID is still alive, refuse.
        if lock.exists():
            try:
                pid = int(lock.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                pid = 0

            if pid > 0 and _pid_is_alive(pid):
                QMessageBox.critical(None, "Already running", "Little Chonker is already running.")
                return None

            # stale lock
            try:
                lock.unlink()
            except Exception:
                pass

        lock.write_text(str(os.getpid()), encoding="utf-8")

        # remove lock on exit
        def _cleanup():
            try:
                if lock.exists():
                    lock.unlink()
            except Exception:
                pass

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_cleanup)  # type: ignore[attr-defined]
        return app
    except Exception:
        # If guard fails, we do NOT block startup.
        logger.exception("Single-instance guard failed (non-fatal).")
        return QApplication.instance()


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        # On Windows: os.kill(pid, 0) works only in newer Pythons / depending on perms.
        # We'll do a conservative best-effort.
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False


# ---------------- Entry ----------------

def main() -> int:
    _configure_env_for_qt()

    # ---- logging ----
    log_dir = _compute_log_dir()
    setup_gui_logging(str(log_dir), filename="app.log")
    logger.info("GUI starting (log_dir=%s)", log_dir)

    # ---- Qt settings ----
    _configure_qt_highdpi()

    # ---- app ----
    app = QApplication(sys.argv)
    app.setApplicationName("Little Chonker")
    app.setOrganizationName("PelliKAn")
    app.setOrganizationDomain("local")

    _maybe_set_app_icon(app)
    _install_exception_hook()

    # guard (prevents double COM open via multiple GUIs)
    # must be called after QApplication exists (for QMessageBox)
    if _single_instance_guard("LittleChonker") is None:
        return 2

    # load config early (so we can warn about monitor settings)
    cfg = _load_general_config_best_effort()
    _sanity_check_monitor_port(cfg)

    # ---- THEME (Single Source of Truth) ----
    # Apply ONE global stylesheet derived from tokens.
    # Frames/widgets must NOT call setStyleSheet; only setProperty(...)
    theme_key = _get_ui_theme_key(cfg)
    apply_theme(app, theme_key)
    logger.info("Theme applied: %s", theme_key)

    # ---- main window ----
    window = MainWindow()
    window.show()

    # Ensure clean shutdown ordering
    try:
        return int(app.exec())
    finally:
        logger.info("GUI stopped")


if __name__ == "__main__":
    raise SystemExit(main())