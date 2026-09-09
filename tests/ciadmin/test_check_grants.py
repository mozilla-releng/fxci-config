# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.appconfig import AppConfig
from tcadmin.resources import Resources, Role, WorkerPool

from ciadmin.check.check_grants import (
    check_run_as_administrator_pools_run_one_task,
)


def resources_for(scope, number_of_tasks=None, worker_pool_id="gecko-t/win11-test"):
    resources = Resources()
    resources.manage(".*")
    with AppConfig._as_current(AppConfig()):
        resources.add(Role(roleId="test", scopes=[scope], description="test"))

        if number_of_tasks is not None:
            resources.add(
                WorkerPool(
                    workerPoolId=worker_pool_id,
                    providerId="test",
                    description="test",
                    owner="test@example.com",
                    emailOnError=False,
                    config={
                        "launchConfigs": [
                            {
                                "workerConfig": {
                                    "genericWorker": {
                                        "config": {
                                            "numberOfTasksToRun": number_of_tasks
                                        }
                                    }
                                }
                            }
                        ]
                    },
                )
            )
    return resources


@pytest.mark.asyncio
async def test_run_as_administrator_pool_runs_one_task():
    resources = resources_for(
        "generic-worker:run-as-administrator:gecko-t/win11-test", 1
    )

    async def generate_resources(*modules):
        return resources

    await check_run_as_administrator_pools_run_one_task(generate_resources)


@pytest.mark.asyncio
async def test_proj_fuzzing_pools_are_ignored():
    resources = resources_for(
        "generic-worker:run-as-administrator:proj-fuzzing/*",
        0,
        "proj-fuzzing/ci-windows",
    )

    async def generate_resources(*modules):
        return resources

    await check_run_as_administrator_pools_run_one_task(generate_resources)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "number_of_tasks"),
    [
        ("generic-worker:run-as-administrator:gecko-t/win11-*", 0),
        ("generic-worker:run-as-administrator:releng-hardware/win11-64*", None),
    ],
)
async def test_rejects_persistent_or_unconfigured_administrator_pool(
    scope, number_of_tasks
):
    resources = resources_for(scope, number_of_tasks)

    async def generate_resources(*modules):
        return resources

    with pytest.raises(AssertionError):
        await check_run_as_administrator_pools_run_one_task(generate_resources)
