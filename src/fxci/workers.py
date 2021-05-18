# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re

import attr
from taskcluster import WorkerManager, optionsFromEnvironment
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_pools import WorkerPool
from ciadmin.generate.worker_pools import generate_pool_variants


def list_workers(worker_pool, states, *, formatter):
    workers = []
    wm = WorkerManager(optionsFromEnvironment())
    wm.listWorkersForWorkerPool(
        worker_pool, paginationHandler=lambda r: workers.extend(r["workers"])
    )

    formatter([worker for worker in workers if worker["state"] in states])


@with_aiohttp_session
async def generate_worker_pools(*, formatter, grep):
    worker_pools = await WorkerPool.fetch_all()
    environment = await Environment.current()

    if grep:
        grep = re.compile(grep)

    def match(pool):
        if grep:
            return grep.match(pool.pool_id)
        return True

    def to_json(worker_pool):
        # attr.asdict generates a dictionary that matches the order of
        # attributes in WorkerPool, so we ask the formatter to not sort keys.
        # However, `pool.config` does not have that structure, so we explictly
        # sort it here.
        result = attr.asdict(worker_pool, filter=lambda a, _: a.name != "variants")
        result["config"] = dict(sorted(result["config"].items()))
        return result

    formatter(
        [
            to_json(pool)
            for pool in sorted(generate_pool_variants(worker_pools, environment))
            if match(pool)
        ],
        sort_keys=False,
    )
