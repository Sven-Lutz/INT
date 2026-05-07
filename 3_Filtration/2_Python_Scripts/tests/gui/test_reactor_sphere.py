"""Unit tests for ReactorSphereWidget._volume_to_fill and related invariants.

The _volume_to_fill helper is a pure function that can be tested without creating
a Qt widget, but importing the widget class itself would spin up PySide6. We import
only the staticmethod from the class via a minimal module load.
"""
from __future__ import annotations

import os
import sys

import pytest

# Ensure src/ is on the path so `from src...` imports resolve.
_HERE = os.path.abspath(os.path.dirname(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(scope="module")
def volume_to_fill():
    """Import the static helper without requiring a QApplication."""
    try:
        from src.gui.frames.right_frame import ReactorSphereWidget
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"PySide6 not importable: {exc}")
    return ReactorSphereWidget._volume_to_fill


class TestVolumeToFill:
    """The non-linear membrane-anchored mapping from volume (mL) to fill (0..1)."""

    def test_zero_volume_is_empty(self, volume_to_fill):
        assert volume_to_fill(0.0, 3500.0, 7000.0) == 0.0

    def test_membrane_volume_is_half(self, volume_to_fill):
        assert volume_to_fill(3500.0, 3500.0, 7000.0) == pytest.approx(0.5)

    def test_max_volume_is_full(self, volume_to_fill):
        assert volume_to_fill(7000.0, 3500.0, 7000.0) == pytest.approx(1.0)

    def test_above_max_clamps_to_one(self, volume_to_fill):
        assert volume_to_fill(10000.0, 3500.0, 7000.0) == 1.0

    def test_negative_volume_clamps_to_zero(self, volume_to_fill):
        assert volume_to_fill(-50.0, 3500.0, 7000.0) == 0.0

    def test_lower_chamber_linear(self, volume_to_fill):
        # Halfway below the membrane → 25% fill.
        assert volume_to_fill(1750.0, 3500.0, 7000.0) == pytest.approx(0.25)

    def test_upper_chamber_linear(self, volume_to_fill):
        # Halfway between membrane and max → 75% fill.
        assert volume_to_fill(5250.0, 3500.0, 7000.0) == pytest.approx(0.75)

    def test_invalid_membrane_returns_zero(self, volume_to_fill):
        assert volume_to_fill(1000.0, 0.0, 7000.0) == 0.0

    def test_membrane_equals_max_returns_zero(self, volume_to_fill):
        # Degenerate config: no upper chamber → cannot express fill > 50%.
        assert volume_to_fill(1000.0, 3500.0, 3500.0) == 0.0

    def test_result_always_in_unit_interval(self, volume_to_fill):
        for v in (-1000.0, 0.0, 100.0, 3500.0, 6999.0, 7000.0, 1e9):
            f = volume_to_fill(v, 3500.0, 7000.0)
            assert 0.0 <= f <= 1.0


class TestUpdateStateConsistency:
    """volume text and fill graphic must always originate from the same number."""

    @pytest.fixture(scope="class")
    def widget(self, qapp):  # noqa: ARG002  (qapp is a pytest-qt fixture)
        from src.gui.frames.right_frame import ReactorSphereWidget
        return ReactorSphereWidget()

    def test_initial_state_is_empty(self, widget):
        assert widget._volume_ml == 0.0
        assert widget._fill_target == 0.0
        assert widget._fill_pct == 0.0

    def test_update_state_syncs_volume_and_fill(self, widget):
        widget.update_state(3500.0, "PHASE_A", membrane_ml=3500.0, max_ml=7000.0)
        assert widget._volume_ml == 3500.0
        assert widget._fill_target == pytest.approx(0.5)

    def test_update_state_clamps_negative_volume(self, widget):
        widget.update_state(-100.0, "IDLE", membrane_ml=3500.0, max_ml=7000.0)
        assert widget._volume_ml == 0.0
        assert widget._fill_target == 0.0

    def test_set_volume_shim_recomputes_fill(self, widget):
        widget.update_state(0.0, "IDLE", membrane_ml=3500.0, max_ml=7000.0)
        widget.set_volume(1750.0)
        assert widget._volume_ml == 1750.0
        assert widget._fill_target == pytest.approx(0.25)
