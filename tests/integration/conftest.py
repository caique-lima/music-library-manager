import os
import tomllib
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires ACOUSTID_API_KEY and network access",
    )


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ACOUSTID_API_KEY"):
        return
    skip = pytest.mark.skip(reason="set ACOUSTID_API_KEY to run AcoustID integration tests")
    for item in items:
        if "integration" in item.keywords and "test_acoustid" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def acoustid_api_key() -> str:
    return os.environ["ACOUSTID_API_KEY"]


def _read_toml_threshold(key: str, env_var: str, default: float) -> float:
    env = os.environ.get(env_var)
    if env:
        return float(env)
    try:
        toml_path = Path(__file__).parents[2] / "pyproject.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return float(data["tool"]["music-manager"][key])
    except Exception:
        return default


@pytest.fixture(scope="session")
def acoustid_accuracy_threshold() -> float:
    """Minimum AcoustID field-match rate. Override via ACOUSTID_ACCURACY_THRESHOLD env var
    or ``tool.music-manager.integration_accuracy_threshold`` in pyproject.toml."""
    return _read_toml_threshold("integration_accuracy_threshold", "ACOUSTID_ACCURACY_THRESHOLD", 0.80)


@pytest.fixture(scope="session")
def shazam_accuracy_threshold() -> float:
    """Minimum Shazam field-match rate. Override via SHAZAM_ACCURACY_THRESHOLD env var
    or ``tool.music-manager.shazam_accuracy_threshold`` in pyproject.toml."""
    return _read_toml_threshold("shazam_accuracy_threshold", "SHAZAM_ACCURACY_THRESHOLD", 0.80)
