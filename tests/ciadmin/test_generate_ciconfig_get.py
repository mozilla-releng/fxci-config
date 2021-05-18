# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.generate.ciconfig.get import _read_file


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_yml():
    res = await _read_file("tests/ciadmin/test.yml")
    assert res == {"test": True}


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_data():
    res = await _read_file("tests/ciadmin/test_generate_ciconfig_get.py")
    assert b"this one weird string" in res
