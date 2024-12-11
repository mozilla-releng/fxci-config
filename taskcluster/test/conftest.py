# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import sys
from pathlib import Path

import pytest
from responses import RequestsMock

here = Path(__file__).parent
sys.path.insert(0, str(here.parent))  # ensure fxci_config_taskgraph is importable

pytest_plugins = ("pytest-taskgraph",)


@pytest.fixture(scope="session")
def datadir():
    return here / "data"


@pytest.fixture
def responses():
    with RequestsMock() as rsps:
        yield rsps
