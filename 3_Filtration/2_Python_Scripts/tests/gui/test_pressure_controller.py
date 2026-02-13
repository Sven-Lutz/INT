import pytest

@pytest.mark.hardware
def test_pressure_controller_init(hw_enabled):
    if not hw_enabled:
        pytest.skip("Hardware test disabled. Use --hw or set PELLIKAN_HW=1")
    from src.hardware.drivers.pressure_controller import PressureController
    _ = PressureController()
