# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_pools import WorkerPool as WorkerPoolConfig
from ciadmin.generate.worker_pools import generate_pool_variants


@pytest.mark.asyncio
async def check_privileged_is_untrusted(generate_resources):
    """
    Ensures that trusted pools (running on a trusted image or trusted provider)
    have privileged config options turned off:

    - for docker-worker, ensure that `allowPrivileged` is disabled
    - for generic-worker, ensure that `enableRunTaskAsCurrentUser` is disabled
    - for d2g, ensure that `allowPrivileged`, `allowGPUs`, `allowInteractive`,
      `allowLoopbackAudio` and `allowLoopbackVideo` are disabled
    """
    environment = await Environment.current()
    worker_pools = await WorkerPoolConfig.fetch_all()
    trusted_pools = set()
    for pool in generate_pool_variants(worker_pools, environment):
        if "trusted" in pool.config.get("image", ""):
            trusted_pools.add(pool.pool_id)
        elif "monopacker" in pool.config.get("image", ""):
            # FIXME ignore monopacker images for now, their generic-worker
            # version doesn't support enableRunTaskAsCurrentUser
            continue
        elif "trusted" in pool.provider_id or "level3" in pool.provider_id:
            trusted_pools.add(pool.pool_id)
    assert trusted_pools

    resources = await generate_resources("worker_pools")
    for pool in resources.filter("WorkerPool=.*"):
        if pool.workerPoolId not in trusted_pools:
            continue
        privileged = False
        for launchConfig in pool.config["launchConfigs"]:
            if (
                launchConfig.get("workerConfig", {})
                .get("dockerConfig", {})
                .get("allowPrivileged", False)
            ):
                privileged = True
                break
            if gwConfig := launchConfig.get("workerConfig", {}).get(
                "genericWorker", {}
            ):
                # generic-worker
                if gwConfig.get("config", {}).get("enableRunTaskAsCurrentUser", True):
                    privileged = True
                    break
                if (
                    gwConfig.get("config", {})
                    .get("d2gConfig", {})
                    .get("enableD2G", False)
                ):
                    d2gConfig = gwConfig["config"]["d2gConfig"]
                    if d2gConfig.get("allowPrivileged", True):
                        privileged = True
                        break
                    # as of v90, allowGPUs defaults to false, but err on the
                    # side of caution here and require that it be explicitly
                    # disabled
                    if d2gConfig.get("allowGPUs", True):
                        privileged = True
                        break
                    if d2gConfig.get("allowInteractive", True):
                        privileged = True
                        break
                    if d2gConfig.get("allowLoopbackAudio", True):
                        privileged = True
                        break
                    if d2gConfig.get("allowLoopbackVideo", True):
                        privileged = True
                        break
        assert not privileged, (
            f"{pool.workerPoolId} has trusted CoT keys, "
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
            # GCP workers have network security at the project/provider level
            ("level3" in pool.provider_id)
            # Azure trusted workers are restricted to the azure_trusted provider
            or ("azure_trusted" in pool.provider_id)
        )
        assert not all([not trusted_security, is_level3_worker(pool)]), (
            f"{pool.pool_id} is a level 3 worker but has unrestricted network access"
        )
