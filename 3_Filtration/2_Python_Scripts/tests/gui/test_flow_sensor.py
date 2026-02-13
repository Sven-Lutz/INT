import os
import pytest
import propar


@pytest.mark.hardware
def test_flow_sensor_reads(hw_enabled):
    if not hw_enabled:
        pytest.skip("Hardware test disabled. Use --hw or set PELLIKAN_HW=1")

    port = os.getenv("PELLIKAN_FLOW_PORT", "COM5")
    flow = propar.instrument(port)

    params = {
        "Volume Flow": {"proc_nr": 33, "parm_nr": 6, "parm_type": propar.PP_TYPE_FLOAT},
        "Normal Flow": {"proc_nr": 33, "parm_nr": 5, "parm_type": propar.PP_TYPE_FLOAT},
        "Totalizer Value": {"proc_nr": 104, "parm_nr": 17, "parm_type": propar.PP_TYPE_FLOAT},
    }

    for name, spec in params.items():
        values = flow.read_parameters([spec])
        assert values, f"No data returned for {name}"
        assert "data" in values[0], f"Missing 'data' for {name}"
        # Nur Smoke-Assertion: muss float-konvertierbar sein
        _ = float(values[0]["data"])
