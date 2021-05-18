# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

"""
taskcluster-worker-runner and generic-worker support having private
configuration stored in taskcluster secrets (`worker-pool:<worker-pool>`).
Typically, this configuration is shared across multiple workers. In order to
facilitate maintaing these secrets, this tool will copy the configuration from
shared secret to each of the appropriate worker-pool secrets.

Currently, only docker-worker requires any secret config. The secret is
`project/releng/docker-worker-secret`, and contains the stateless hostname
secret.

See [Bug 1598444](https://bugzilla.mozilla.org/show_bug.cgi?id=1598444) for a better
solution for this.
"""

import sys

from taskcluster import optionsFromEnvironment
from taskcluster.aio import Secrets
from taskcluster.utils import fromNow
from tcadmin.util.sessions import aiohttp_session, with_aiohttp_session

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_pools import WorkerPool
from ciadmin.generate.worker_pools import generate_pool_variants


async def list_secrets():
    secrets_api = Secrets(optionsFromEnvironment(), session=aiohttp_session())
    secrets = set()
    await secrets_api.list(
        paginationHandler=lambda response: secrets.update(response["secrets"])
    )
    return secrets


async def docker_worker_pools():
    docker_pools = set()
    environment = await Environment.current()
    worker_pools = await WorkerPool.fetch_all()
    for worker_pool in generate_pool_variants(worker_pools, environment):
        implementation = worker_pool.config.get("implementation", "docker-worker")
        if implementation == "docker-worker":
            docker_pools.add(worker_pool.pool_id)

    return docker_pools


@with_aiohttp_session
async def create_worker_secrets(*, update):
    docker_pools = await docker_worker_pools()

    secrets_api = Secrets(optionsFromEnvironment(), session=aiohttp_session())

    docker_worker_secret = (
        await secrets_api.get("project/releng/docker-worker-secret")
    )["secret"]

    expiry = fromNow("1000y")
    for worker_pool in sorted(docker_pools):
        # bhearsum's hack to workaround this worker pool
        # getting the stateless secret, which is not supported
        # by that pool.
        if "gecko-t-osx-dtk-dev" in worker_pool:
            continue
        secret_name = "worker-pool:{}".format(worker_pool)
        try:
            old_secret = await secrets_api.get(secret_name)
            if old_secret["secret"] == docker_worker_secret:
                continue
            if update:
                await secrets_api.set(
                    secret_name, {"secret": docker_worker_secret, "expires": expiry}
                )
            else:
                print("{} secret is different".format(secret_name))
        except Exception:
            print("Creating {}".format(secret_name))
            await secrets_api.set(
                secret_name, {"secret": docker_worker_secret, "expires": expiry}
            )


@with_aiohttp_session
async def check_worker_secrets():
    secrets = await list_secrets()

    docker_pools = await docker_worker_pools()
    missing_secrets = set()

    for worker_pool in docker_pools:
        secret_name = "worker-pool:{}".format(worker_pool)
        if secret_name not in secrets:
            missing_secrets.add(secret_name)

    if missing_secrets:
        print("Missing secrets for workers:")
        for secret in sorted(missing_secrets):
            print(secret)
        sys.exit(1)
