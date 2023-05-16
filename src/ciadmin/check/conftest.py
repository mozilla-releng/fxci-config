# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import inspect
from collections import defaultdict

import pytest
from tcadmin.resources import Resources
from tcadmin.util.scopes import Resolver
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.boot import appconfig


# Imported from pytest-asyncio, but with scope session
# https://github.com/pytest-dev/pytest-asyncio/issues/75
@pytest.fixture(scope="session")
def event_loop(request):
    """Create an instance of the default event loop for each test run."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def generate_resources():
    """Generate and return a subset of resources.

    This function will generate resources lazily. Subsequent calls will return
    cached results for the modules that have already been generated.
    """
    cache = {}

    @with_aiohttp_session
    async def inner(*modules):
        callables = {
            inspect.getmodule(func).__name__.rsplit(".", 1)[-1]: func
            for func in appconfig.generators
        }
        if modules:
            callables = {
                name: func for name, func in callables.items() if name in modules
            }

        # Because resources are modified by the callables in-place, we
        # need to create seperate variables to track the result of each
        # callable.
        resources = defaultdict(lambda: Resources())
        tasks = []
        for name, func in callables.items():
            if name in cache:
                resources[name] = cache[name]
            else:
                r = resources[name]
                r.manage(".*")
                tasks.append(asyncio.create_task(func(r)))

        await asyncio.gather(*tasks)
        # Apply modifiers.
        for mod in appconfig.modifiers:
            resources = {k: await mod(v) for k, v in resources.items()}

        cache.update(resources)

        # Gather resources from each module back together.
        all_resources = Resources()
        all_resources.manage(".*")
        for r in resources.values():
            all_resources.update(r)

        return all_resources

    return inner


@pytest.fixture(scope="session")
async def generated(generate_resources):
    """Return the generated resources"""
    return await generate_resources()


@pytest.fixture(scope="session")
async def actual(generated):
    """Return the actual resources (as fetched from Taskcluster)"""
    return await current.resources(generated.managed)


@pytest.fixture(scope="session")
def generated_resolver(generated):
    return Resolver.from_resources(generated)


@pytest.fixture(scope="session")
def queue_priorities():
    return "highest very-high high medium low very-low lowest normal".split()
