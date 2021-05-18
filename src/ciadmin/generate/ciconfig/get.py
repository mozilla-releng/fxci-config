# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from asyncio import Lock

import yaml

_cache = {}
_lock = {}


async def _read_file(filename, **test_kwargs):
    with open(filename, "rb") as f:
        result = f.read()

    if filename.endswith(".yml"):
        result = yaml.safe_load(result)

    return result


async def get_ciconfig_file(filename):
    """
    Get the named file from the ci-configuration repository, parsing .yml if necessary.

    Fetches are cached, so it's safe to call this many times for the same file.
    """
    async with _lock.setdefault(filename, Lock()):
        if filename in _cache:
            return _cache[filename]

        _cache[filename] = await _read_file(filename)
        return _cache[filename]
