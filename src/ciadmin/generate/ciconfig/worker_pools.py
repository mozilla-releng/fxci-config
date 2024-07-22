# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import attr

from .get import get_ciconfig_file


@attr.s(frozen=True)
class WorkerPool:
    pool_id: str = attr.ib(type=str)
    description: str = attr.ib(type=str)
    owner: str = attr.ib(type=str)
    email_on_error: bool = attr.ib(type=bool)
    provider_id: str = attr.ib(type=str)
    config: dict = attr.ib(type=dict)
    attributes: dict = attr.ib(factory=dict)
    variants: list = attr.ib(factory=lambda: [{}])

    @pool_id.validator
    def _check_pool_id(self, attribute, value):
        if value.count("/") != 1:
            raise ValueError(
                "Worker pool_id must be of the form `provisionerId/workerPool`, "
                f"not {value}"
            )

    @staticmethod
    async def fetch_all():
        """Load worker-type metadata from worker-pools.yml in ci-configuration"""
        config = await get_ciconfig_file("worker-pools.yml")

        return [WorkerPool(**info) for info in config["pools"]]
