from pathlib import Path
from src.utils.config_manager import ConfigManager


def test_default_configs_exist():
    root = Path(__file__).resolve().parents[2]
    defaults_dir = root / "src" / "config" / "defaults"

    assert defaults_dir.exists(), "defaults directory missing"

    yaml_files = list(defaults_dir.glob("*.yaml"))
    assert yaml_files, "no default yaml files found"

    for p in yaml_files:
        assert p.read_text().strip(), f"{p.name} is empty"
