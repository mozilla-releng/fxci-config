# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.appconfig import AppConfig
from tcadmin.resources import Resources, Role, WorkerPool
from tcadmin.util.matchlist import Match, MatchList

from ciadmin.check import check_grants
from ciadmin.check.check_grants import (
    check_grant_pools,
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
async def test_test_provisioner_scopes_are_ignored():
    resources = resources_for("generic-worker:run-as-administrator:test-provisioner/*")

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


class _Grant:
    def __init__(self, scopes):
        self.scopes = scopes


async def _check_grant_pools(monkeypatch, scope):
    async def fetch_all():
        return [_Grant([scope])]

    monkeypatch.setattr(check_grants.Grant, "fetch_all", fetch_all)
    resources = resources_for("unused", 0, "gecko-t/win11-test")

    async def generate_resources(*modules):
        return resources

    await check_grant_pools(generate_resources)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pool",
    [
        # pools we generate
        "gecko-t/win11-test",
        "gecko-t/win11-*",
        # pools we don't manage, which can't be validated
        "proj-fuzzing/ci-decision",
        "proj-fuzzing/foo-*",
        "proj-fuzzing/*",
    ],
)
async def test_grant_pools_accepts(monkeypatch, pool):
    await _check_grant_pools(monkeypatch, f"queue:create-task:highest:{pool}")


@pytest.mark.asyncio
async def test_grant_pools_accepts_os_group_of_unmanaged_pool(monkeypatch):
    await _check_grant_pools(
        monkeypatch, "generic-worker:os-group:proj-fuzzing/foo/Administrators"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pool",
    [
        # managed, but not generated
        "gecko-t/no-such-pool",
        "proj-fuzzing/decision",
        # matches no generated pool and can't refer to an unmanaged one
        "gecko-t/no-such-*",
        "proj-fuzzingx/foo",
    ],
)
async def test_grant_pools_rejects(monkeypatch, pool):
    with pytest.raises(AssertionError):
        await _check_grant_pools(monkeypatch, f"queue:create-task:highest:{pool}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pool,valid",
    [
        ("other/x", True),
        ("other/x*", True),
        # every pool ID starting with this is managed, so it must be generated
        ("other/xy*", False),
    ],
)
async def test_grant_pools_exact_exclude(monkeypatch, pool, valid):
    "A pattern can only refer to an excluded pool whose whole ID it can match"
    monkeypatch.setattr(
        check_grants,
        "managed",
        MatchList([Match("WorkerPool=.*", excludes=["WorkerPool=other/x"])]),
    )
    scope = f"queue:create-task:highest:{pool}"
    if valid:
        await _check_grant_pools(monkeypatch, scope)
    else:
        with pytest.raises(AssertionError):
            await _check_grant_pools(monkeypatch, scope)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pool,valid",
    [
        # no include covers these, so they're unmanaged
        ("other/foo", True),
        ("other/foo-*", True),
        # managed, and no generated pool starts with this
        ("gecko-t/no-such-*", False),
    ],
)
async def test_grant_pools_outside_includes(monkeypatch, pool, valid):
    "Pools that no include matches are unmanaged"
    monkeypatch.setattr(check_grants, "managed", MatchList(["WorkerPool=gecko-t/.*"]))
    scope = f"queue:create-task:highest:{pool}"
    if valid:
        await _check_grant_pools(monkeypatch, scope)
    else:
        with pytest.raises(AssertionError):
            await _check_grant_pools(monkeypatch, scope)
