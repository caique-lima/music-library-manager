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
    skip = pytest.mark.skip(reason="set ACOUSTID_API_KEY to run integration tests")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def acoustid_api_key() -> str:
    return os.environ["ACOUSTID_API_KEY"]


@pytest.fixture(scope="session")
def acoustid_accuracy_threshold() -> float:
    """Minimum fraction of field checks that must pass across all fixtures.

    Override via ACOUSTID_ACCURACY_THRESHOLD env var or
    ``tool.music-manager.integration_accuracy_threshold`` in pyproject.toml.
    """
    env = os.environ.get("ACOUSTID_ACCURACY_THRESHOLD")
    if env:
        return float(env)
    try:
        toml_path = Path(__file__).parents[2] / "pyproject.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return float(data["tool"]["music-manager"]["integration_accuracy_threshold"])
    except Exception:
        return 0.80
