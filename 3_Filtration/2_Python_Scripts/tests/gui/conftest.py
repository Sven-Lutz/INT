import os
import sys
from pathlib import Path
import pytest


HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
SRC = ROOT / "src"

if not SRC.exists():
    raise RuntimeError(f"Expected src/ at {SRC}, but it does not exist. Check conftest ROOT calculation.")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--hw", action="store_true", default=False, help="Enable hardware tests")


@pytest.fixture(scope="session")
def hw_enabled(pytestconfig: pytest.Config) -> bool:
    return bool(pytestconfig.getoption("--hw")) or os.getenv("PELLIKAN_HW", "0") == "1"
