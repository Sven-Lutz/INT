from __future__ import annotations

from control.empty_detection import (
    CapacitanceState,
    EmptyDetectionSettings,
    EmptyDetector,
)
from devices.sensors import CapacitanceScaling, HumidityScaling


def test_classification() -> None:
    settings = EmptyDetectionSettings(
        empty_threshold=2.0,
        filled_threshold=12.5,
    )

    assert (
        settings.classify(24.7) == CapacitanceState.FILLED
    )
    assert (
        settings.classify(8.0) == CapacitanceState.DRAINING
    )
    assert settings.classify(1.4) == CapacitanceState.EMPTY
    assert (
        settings.classify(None) == CapacitanceState.UNKNOWN
    )

    print("Capacitance states classified correctly.")


def test_debounce() -> None:
    detector = EmptyDetector(
        EmptyDetectionSettings(
            empty_threshold=2.0,
            consecutive_samples=3,
        )
    )

    assert detector.update(25.0) is False
    assert detector.update(1.0) is False
    assert detector.update(1.0) is False

    # A single value back above the threshold resets the counter, so one
    # noisy sample cannot stop the process.
    assert detector.update(20.0) is False
    assert detector.below_threshold_count == 0

    assert detector.update(1.0) is False
    assert detector.update(0.5) is False
    assert detector.update(0.2) is True
    assert detector.triggered is True
    assert detector.state == CapacitanceState.EMPTY

    print("Empty stop triggered after 3 consecutive samples.")


def test_disabled_detector() -> None:
    detector = EmptyDetector(
        EmptyDetectionSettings(
            empty_threshold=2.0,
            consecutive_samples=2,
            enabled=False,
        )
    )

    assert detector.update(0.1) is False
    assert detector.update(0.1) is False
    assert detector.triggered is False

    # The state is still reported even when the stop is disabled.
    assert detector.state == CapacitanceState.EMPTY

    print("Disabled empty stop never triggers.")


def test_missing_values() -> None:
    detector = EmptyDetector(
        EmptyDetectionSettings(consecutive_samples=2)
    )

    assert detector.update(0.1) is False
    assert detector.update(None) is False
    assert detector.below_threshold_count == 0
    assert detector.state == CapacitanceState.UNKNOWN

    print("Missing readings do not trigger the empty stop.")


def test_capacitance_scaling() -> None:
    scaling = CapacitanceScaling(
        value_per_volt=2.5,
        offset=-1.0,
    )

    assert scaling.to_value(10.0) == 24.0
    assert scaling.to_value(None) is None

    print("Capacitance scaling applied correctly.")


def test_humidity_scaling() -> None:
    scaling = HumidityScaling(
        voltage_at_0_percent=0.0,
        voltage_at_100_percent=10.0,
    )

    assert scaling.to_percent(0.0) == 0.0
    assert scaling.to_percent(4.5) == 45.0
    assert scaling.to_percent(10.0) == 100.0

    # Readings outside the calibrated range are clamped so the plot
    # stays inside its 0-100 % axis.
    assert scaling.to_percent(-1.0) == 0.0
    assert scaling.to_percent(12.0) == 100.0
    assert scaling.to_percent(None) is None

    print("Humidity converted to percent correctly.")


def main() -> None:
    test_classification()
    test_debounce()
    test_disabled_detector()
    test_missing_values()
    test_capacitance_scaling()
    test_humidity_scaling()
    print("All empty-detection tests passed.")


if __name__ == "__main__":
    main()
