# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re

import pytest

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_pools import WorkerPool as WorkerPoolConfig
from ciadmin.generate.worker_pools import generate_pool_variants

WORKER_POOL_ID_RE = re.compile(
    r"^[a-zA-Z0-9-_]{1,38}\/[a-z]([-a-z0-9]{0,36}[a-z0-9])?$"
)


@pytest.mark.asyncio
async def check_worker_pool_ids(generated):
    invalid_pools = set()

    environment = await Environment.current()
    worker_pools = await WorkerPoolConfig.fetch_all()
    for pool in generate_pool_variants(worker_pools, environment):
        if not WORKER_POOL_ID_RE.match(pool.pool_id):
            invalid_pools.add(pool.pool_id)

    if invalid_pools:
        print(
            f"Worker pool ids must match /{WORKER_POOL_ID_RE.pattern}/! "
            + "The following pool ids are invalid:\n"
            + "\n".join(sorted(invalid_pools))
        )

    assert not invalid_pools
