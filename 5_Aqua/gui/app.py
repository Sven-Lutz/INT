from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from config import MEASUREMENT_DIRECTORY, create_required_directories, validate_configuration
from gui.logging_bridge import configure_runtime_logging
from gui.main_window import ProcessControlWindow
from gui.runtime import ProcessRuntime
from gui.theme import AQUA_STYLESHEET
from main import build_controller


__all__ = ["ProcessControlWindow", "main"]


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Aqua Process Control")
    application.setOrganizationName("Aqua")
    application.setStyle("Fusion")
    application.setStyleSheet(AQUA_STYLESHEET)

    window = ProcessControlWindow()
    runtime_log_path = MEASUREMENT_DIRECTORY / "aqua_runtime.log"
    logger, qt_log_handler = configure_runtime_logging(
        runtime_log_path
    )
    qt_log_handler.emitter.record_received.connect(
        window.append_runtime_log
    )

    runtime: ProcessRuntime | None = None
    try:
        validate_configuration()
        create_required_directories()
        controller = build_controller()
        runtime = ProcessRuntime(
            controller,
            runtime_log_path=runtime_log_path,
        )

        window.connect_requested.connect(runtime.connect_hardware)
        window.disconnect_requested.connect(runtime.disconnect_hardware)
        window.start_requested.connect(runtime.start_process)
        window.stop_requested.connect(runtime.stop_process)
        window.led_requested.connect(runtime.set_led)

        runtime.state_changed.connect(window.set_process_state)
        runtime.start_interlock_changed.connect(window.set_start_pending)
        runtime.run_started.connect(window.mark_run_started)
        runtime.run_finished.connect(window.show_run_summary)
        runtime.developer_snapshot.connect(window.update_developer_snapshot)
        runtime.telemetry_received.connect(
            lambda measurement, elapsed, total_volume, is_running: (
                window.update_measurement(
                    measurement,
                    elapsed_seconds=elapsed,
                    total_volume_ml=total_volume,
                    append_to_charts=is_running,
                )
            )
        )
        application.aboutToQuit.connect(runtime.shutdown)
        logger.info("Aqua operator GUI initialized")

    except Exception as exc:
        logging.getLogger("aqua").exception("Aqua GUI initialization failed")
        window.set_configuration_error(str(exc))

    window.show()
    exit_code = application.exec()

    # Keep objects alive until Qt has completed its shutdown path.
    _ = runtime
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
