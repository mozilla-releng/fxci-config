# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from ciadmin.generate.ciconfig.worker_pools import WorkerPool


@pytest.mark.asyncio
async def test_fetch_empty(mock_ciconfig_file):
    mock_ciconfig_file("worker-pools.yml", {"pools": []})
    assert await WorkerPool.fetch_all() == []


@pytest.mark.asyncio
async def test_fetch_entry(mock_ciconfig_file):
    mock_ciconfig_file(
        "worker-pools.yml",
        {
            "pools": [
                {
                    "pool_id": "provId/my-worker-pool",
                    "description": "a test workerpool",
                    "owner": "me@example.com",
                    "provider_id": "skyy-cloud-services",
                    "config": {"some-config": True},
                    "email_on_error": False,
                },
            ],
        },
    )
    assert await WorkerPool.fetch_all() == [
        WorkerPool(
            pool_id="provId/my-worker-pool",
            description="a test workerpool",
            owner="me@example.com",
            provider_id="skyy-cloud-services",
            config={"some-config": True},
            email_on_error=False,
        )
    ]


@pytest.mark.asyncio
async def test_fetch_invalid_name(mock_ciconfig_file):
    mock_ciconfig_file(
        "worker-pools.yml",
        {
            "pools": [
                {
                    "pool_id": "my-worker-pool",
                    "description": "a test workerpool",
                    "owner": "me@example.com",
                    "provider_id": "skyy-cloud-services",
                    "config": {"some-config": True},
                    "email_on_error": False,
                },
            ],
        },
    )
    with pytest.raises(ValueError):
        await WorkerPool.fetch_all()
