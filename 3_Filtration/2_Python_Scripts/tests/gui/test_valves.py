import pytest

@pytest.mark.hardware
def test_valves_all_open(hw_enabled):
    if not hw_enabled:
        pytest.skip("Hardware test disabled. Use --hw or set PELLIKAN_HW=1")
    from src.hardware.drivers.valves import ValveController
    valve_ctrl = ValveController()
    valve_ctrl.all_open()
