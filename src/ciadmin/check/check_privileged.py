# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.resources import WorkerPool
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_pools import WorkerPool as WorkerPoolConfig
from ciadmin.generate.worker_pools import generate_pool_variants


@pytest.mark.asyncio
@with_aiohttp_session
async def check_privileged_is_untrusted(generated):
    """
    Ensures that any docker-worker pool with `allowPrivileged` is not
    run on a trusted image.
    """
    worker_pools = await WorkerPoolConfig.fetch_all()
    trusted_pools = set()
    for pool in worker_pools:
        if "trusted" in pool.config.get("image", ""):
            trusted_pools.add(pool.pool_id)

    for resource in generated:
        if not isinstance(resource, WorkerPool):
            continue
        if resource.workerPoolId not in trusted_pools:
            continue
        privileged = False
        for launchConfig in resource.config["launchConfigs"]:
            if (
                launchConfig.get("workerConfig", {})
                .get("dockerConfig", {})
                .get("allowPrivileged", False)
            ):
                privileged = True
        assert not privileged, (
            f"{pool.pool_id} has trusted CoT keys, "
            + "but permits privileged (host-root-equivalent) tasks."
        )


def is_level3_worker(pool):
    pool_group, pool_id = pool.pool_id.split("/", 1)
    return pool_group.endswith("-3")


@pytest.mark.asyncio
@with_aiohttp_session
async def check_trusted_level_3_workers():
    """
    Ensures that any trusted images are only used in level 3 workers.
    """
    environment = await Environment.current()
    worker_pools = await WorkerPoolConfig.fetch_all()
    for pool in generate_pool_variants(worker_pools, environment):
        trusted = "trusted" in pool.config.get("image", "")
        pool_group, pool_id = pool.pool_id.split("/", 1)
        assert not all([trusted, not is_level3_worker(pool)]), (
            f"{pool.pool_id} has trusted CoT keys, "
            "but does not appear to be restricted to level 3 tasks"
        )


@pytest.mark.asyncio
@with_aiohttp_session
async def check_level_3_worker_security():
    """
    Ensures that all level 3 workers have appropriate security groups.
    """
    environment = await Environment.current()
    worker_pools = await WorkerPoolConfig.fetch_all()
    for pool in generate_pool_variants(worker_pools, environment):
        trusted_security = (
            ("trusted" == pool.config.get("security", "untrusted"))
            # GCP workers have networker security at the project/provider level
            or ("level3" in pool.provider_id)
        )
        assert not all([not trusted_security, is_level3_worker(pool)]), (
            f"{pool.pool_id} is a level 3 worker but has "
            f"unrestricted network access"
        )
