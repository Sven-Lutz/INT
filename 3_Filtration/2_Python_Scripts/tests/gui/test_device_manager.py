import pytest

@pytest.mark.hardware
def test_device_manager_smoke(hw_enabled):
    if not hw_enabled:
        pytest.skip("Hardware test disabled. Use --hw or set PELLIKAN_HW=1")
    from src.backend.core.device_manager import DeviceManager
    dvm = DeviceManager()
    dvm.all_valves_shut()
