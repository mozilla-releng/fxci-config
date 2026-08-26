# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
from collections import defaultdict

import click
import pytest
from tcadmin import current
from tcadmin.resources import Resources
from tcadmin.util.scopes import Resolver
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.boot import RESOURCE_MODULES, appconfig
from ciadmin.util.generated import filter_generated, load_generated


def _generated_path():
    """Return the path passed via tc-admin's `--generated` flag, if any."""
    try:
        ctx = click.get_current_context()
    except RuntimeError:
        return None
    return ctx.params.get("generated")


@pytest.fixture(scope="session")
async def generate_resources():
    """Generate and return a subset of resources.

    This function will generate resources lazily. Subsequent calls will return
    cached results for the modules that have already been generated.

    If `tc-admin check --generated PATH` was used, the resources are instead
    loaded once from PATH and module filtering is then done by matching each
    resource's id against the requested modules' `managed` MatchLists.
    """
    cache = {}
    generated_path = _generated_path()

    @with_aiohttp_session
    async def inner(*modules):
        if generated_path:
            if "resources" not in cache:
                cache["resources"] = load_generated(generated_path)
            return filter_generated(cache["resources"], modules, RESOURCE_MODULES)

        callables = dict(appconfig.generators.callables)
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
