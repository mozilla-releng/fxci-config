# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import inspect
from collections import defaultdict

import pytest
import tcadmin.generate
from tcadmin import current
from tcadmin.resources import Resources
from tcadmin.util.scopes import Resolver
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.boot import appconfig, filter_resources_by_modules


@pytest.fixture(scope="session")
async def generate_resources():
    """Generate and return a subset of resources.

    This function will generate resources lazily. Subsequent calls will return
    cached results for the modules that have already been generated.
    """
    module_cache = {}
    generated_cache = []

    @with_aiohttp_session
    async def inner(*modules):
        # tc-admin's `--generated` flag loads a complete resource set from a
        # cache file rather than running generators live, so there's nothing
        # to gain by only generating a subset of modules. Narrow it down to
        # the requested module(s) here instead.
        if appconfig.options.get("generated"):
            if not generated_cache:
                generated_cache.append(await tcadmin.generate.resources())
            resources = generated_cache[0]
            if modules:
                gen_modules = (inspect.getmodule(func) for func in appconfig.generators)
                gen_modules = {
                    mod.__name__.rsplit(".", 1)[-1]: mod for mod in gen_modules
                }
                resources = await filter_resources_by_modules(
                    resources, [gen_modules[m] for m in modules]
                )
            return resources

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
            if name in module_cache:
                resources[name] = module_cache[name]
            else:
                r = resources[name]
                r.manage(".*")
                tasks.append(asyncio.create_task(func(r)))

        await asyncio.gather(*tasks)
        # Apply modifiers.
        for mod in appconfig.modifiers:
            resources = {k: await mod(v) for k, v in resources.items()}

        module_cache.update(resources)

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
