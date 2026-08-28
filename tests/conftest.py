import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common import config as config_mod  # noqa: E402
from src.testing import synth  # noqa: E402

# Small enough to keep the suite fast, large enough that the injected faults
# clear the min_n threshold.
SMALL = dict(days=1, n_heads=8, closure_interval_seconds=30.0)


@pytest.fixture(scope="session")
def synthetic():
    """(events, ground_truth) for a small deterministic pool."""
    return synth.generate(**SMALL)


@pytest.fixture(scope="session")
def events(synthetic):
    return synthetic[0]


@pytest.fixture(scope="session")
def ground_truth(synthetic):
    return synthetic[1]


@pytest.fixture(scope="session")
def faults(ground_truth):
    return {f["type"]: f for f in ground_truth["faults"]}


@pytest.fixture
def cfg():
    conf = config_mod.load()
    conf["data"]["synthetic"] = {**conf["data"]["synthetic"], **SMALL}
    return conf
