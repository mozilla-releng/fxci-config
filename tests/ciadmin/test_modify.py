# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import AsyncMock

import pytest

from ciadmin import boot, modify
from ciadmin.util import github


@pytest.mark.asyncio
async def test_close_github_client_closes_and_passes_resources_through(monkeypatch):
    closed = AsyncMock()
    monkeypatch.setattr(github, "close_client", closed)
    resources = object()

    assert await modify.close_github_client(resources) is resources
    closed.assert_awaited_once()


def test_the_client_is_closed_even_when_the_environment_is_rejected():
    """The teardown has to run before the modifier that can reject the run.

    `modify_resources` raises on a rootUrl mismatch, and a modifier that raises
    stops the ones behind it -- which would leak the client on exactly the runs
    that already went wrong.
    """
    registered = [m.__name__ for m in boot.appconfig.modifiers]

    assert registered.index("close_github_client") < registered.index(
        "modify_resources"
    )
