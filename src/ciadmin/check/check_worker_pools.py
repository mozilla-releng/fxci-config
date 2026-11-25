# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import re
from functools import lru_cache
from textwrap import dedent

import pytest
from google.cloud.compute import (
    ListMachineTypesRequest,
    ListZonesRequest,
    MachineTypesClient,
    ZonesClient,
)
from google.oauth2 import service_account

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_pools import WorkerPool as WorkerPoolConfig
from ciadmin.generate.worker_pools import generate_pool_variants

WORKER_POOL_ID_RE = re.compile(
    r"^[a-zA-Z0-9-_]{1,38}\/[a-z]([-a-z0-9]{0,36}[a-z0-9])?$"
)


@pytest.mark.asyncio
async def check_worker_pool_ids():
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


@pytest.mark.asyncio
async def check_worker_pool_tags(generate_resources):
    invalid_pools = set()

    resources = await generate_resources("worker_pools")
    for pool in resources.filter("WorkerPool=.*"):
        for lc in pool.config.get("launchConfigs", []):
            tags = lc.get("tags", {})

            if any(not isinstance(t, str) for t in tags.values()):
                invalid_pools.add(pool.workerPoolId)
                break

    if invalid_pools:
        print(
            "Worker pool tags must be strings! "
            + "The following pool ids have invalid tags:\n"
            + "\n".join(sorted(invalid_pools))
        )

    assert not invalid_pools


@pytest.mark.asyncio
async def check_providers():
    invalid_pools = set()
    missing_providers = set()

    environment = await Environment.current()
    worker_pools = await WorkerPoolConfig.fetch_all()
    for pool in generate_pool_variants(worker_pools, environment):
        if pool.provider_id == "static":
            continue
        if pool.provider_id not in environment.worker_manager["providers"]:
            invalid_pools.add(pool.pool_id)
            missing_providers.add(pool.provider_id)

    if invalid_pools:
        print(
            f"Worker pool providers must be defined in environments.yml.\n"
            f"The following pools use unknown providers:\n"
            f"Pools: {', '.join(invalid_pools)}\n"
            f"Provider ids: {', '.join(missing_providers)}\n"
        )

    assert not invalid_pools


@pytest.mark.asyncio
async def check_d2g_disables_native_payloads(generate_resources):
    """
    Ensures that any pool with d2g enabled (`d2gConfig.enableD2G`) also disables
    native (generic-worker) payloads (`disableNativePayloads`).

    `disableNativePayloads` defaults to false in generic-worker, so it must be
    set explicitly to true.
    """
    # The taskcluster team's own CI and staging image pools intentionally run
    # both native and d2g-translated payloads to exercise generic-worker itself.
    ignore = (
        "proj-taskcluster/ci",
        "proj-taskcluster/release",
        "proj-taskcluster/gw-ubuntu-24-04",
        "proj-taskcluster/gw-ubuntu-24-04-gui",
        "proj-taskcluster/gw-ubuntu-staging-google",
        "proj-taskcluster/gw-ubuntu-arm64-staging-google",
    )
    invalid_pools = set()

    resources = await generate_resources("worker_pools")
    for pool in resources.filter("WorkerPool=.*"):
        if pool.workerPoolId in ignore:
            continue
        for launchConfig in pool.config.get("launchConfigs", []):
            config = (
                launchConfig.get("workerConfig", {})
                .get("genericWorker", {})
                .get("config", {})
            )
            if config.get("d2gConfig", {}).get("enableD2G", False) and not config.get(
                "disableNativePayloads", False
            ):
                invalid_pools.add(pool.workerPoolId)
                break

    if invalid_pools:
        print(
            "Pools with d2g enabled (d2gConfig.enableD2G) must also set "
            "disableNativePayloads: true. The following pools do not:\n"
            + "\n".join(sorted(invalid_pools))
        )

    assert not invalid_pools


GCP_MACHINE_TYPE_REGEX = re.compile(
    r"""
    ^(?P<machine_series>[^-]+)
    -(?P<machine_configuration>[^-]+)
    (-(?P<number_of_cpus>\d+)
    (-(?P<suffix>.+))?)?
    $""",
    re.VERBOSE,
)


def min_scratch_disks(machine_type):
    """Return the minimum number of scratch disks based on machine_type.

    As documented at:
    https://cloud.google.com/compute/docs/disks/local-ssd#choose_number_local_ssds
    """
    matches = GCP_MACHINE_TYPE_REGEX.match(machine_type)
    if matches is None:
        raise ValueError(f"Cannot parse '{machine_type}'")

    machine_series = matches.group("machine_series")
    if machine_series not in (
        "g1",
        "n1",
        "n2",
        "n2d",
        "c2",
        "c2d",
        "c3d",
        "c4d",
        "t2a",
    ):
        raise NotImplementedError(
            f"Min scratch disks not implemented for '{machine_type}'"
        )

    # t2a ARM64 machines don't support Local SSD disks.
    if machine_series == "t2a":
        return 0

    if machine_series == "n1":
        return 1

    if machine_series == "g1":
        return 0

    if not matches.group("number_of_cpus"):
        raise ValueError(f"Expected CPU count as part of {machine_type}")

    num_cpu = int(matches.group("number_of_cpus"))
    if machine_series in ("c2", "n2", "n2d"):
        powers_of_2 = tuple(2**i for i in range(0, 4))
        for i in powers_of_2:
            if num_cpu <= i * 10:
                return i

    # TODO: c4d doesn't have a documented limit for local SSDs.
    # https://cloud.google.com/compute/docs/general-purpose-machines#c4d-standard-with-local-ssd
    elif machine_series in ("c2d", "c3d", "c4d"):
        # https://cloud.google.com/compute/docs/compute-optimized-machines#c2d_machine_types
        # https://cloud.google.com/compute/docs/general-purpose-machines#c3d-standard-with-local-ssd
        if num_cpu <= 16:
            return 1
        elif num_cpu <= 32:
            return 2
        elif num_cpu <= 60:
            return 4
        elif num_cpu <= 360:
            return 8

    return 16


@pytest.mark.asyncio
async def check_gcp_ssds():
    """This test aims to avoid requesting unnecessary SSDs."""
    environment = await Environment.current()
    worker_pools = await WorkerPoolConfig.fetch_all()
    ignore = (
        # Bug 1962119: Let's keep the number of local SSDs the same between
        # c2 and its AMD counterpart.
        "gecko-1/b-linux-gcp-bug1962119-c2d",
        "gecko-1/b-linux-gcp-bug1962119-c4d",
    )
    errors = []

    for pool in generate_pool_variants(worker_pools, environment):
        if "gcp" not in pool.provider_id:
            continue

        for instance in pool.config["instance_types"]:
            num_disks = len(
                [
                    disk
                    for disk in instance["disks"]
                    if disk["type"].lower() == "scratch"
                ]
            )
            if not num_disks:
                continue
            min_disks = min_scratch_disks(instance["machine_type"])

            if num_disks < min_disks:
                errors.append(
                    f"{pool.pool_id}: defines {num_disks}, but requires at least "
                    f"{min_disks}"
                )
            if num_disks > min_disks and pool.pool_id not in ignore:
                errors.append(
                    f"{pool.pool_id}: defines {num_disks}, only needs {min_disks}"
                )

    if errors:
        print(
            dedent(
                """
        Some pools have more SSDs than necessary!

          {errors}

        If these extra SSDs were added intentionally,
        add the pool id to the ignore list of this test.
        """
            )
            .format(errors="\n  ".join(sorted(errors)))
            .lstrip()
        )
    assert not errors


class GCPApiHandler:
    def __init__(self, token):
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(token)
        )
        self.credentials = credentials
        self.project_id = credentials.project_id
        self.machine_types_client = MachineTypesClient(credentials=credentials)
        self.zones_client = ZonesClient(credentials=credentials)

    def list_zones(self):
        request = ListZonesRequest(project=self.project_id)
        return set(zone.name for zone in self.zones_client.list(request=request))

    @lru_cache
    def list_machine_types(self, zone):
        request = ListMachineTypesRequest(project=self.project_id, zone=zone)
        return set(m.name for m in self.machine_types_client.list(request=request))


@pytest.mark.asyncio
async def check_worker_pool_gcp_instances_by_region(generate_resources):
    gcp_token = os.getenv("GCP_CHECK_TOKEN", None)
    if not gcp_token:
        return pytest.skip("GCP_CHECK_TOKEN not set")

    gcp_api = GCPApiHandler(gcp_token)

    invalid_zones = []
    invalid_machine_types = []
    gcp_zones = gcp_api.list_zones()

    resources = await generate_resources("worker_pools")
    for pool in resources.filter("WorkerPool=.*"):
        if "gcp" not in pool.providerId:
            continue
        # Collect zones to query GCP
        for machine in pool.config["launchConfigs"]:
            machine_type = machine["machineType"].split("/")[-1]
            if "custom" in machine_type:
                continue  # Skip custom machine types
            if machine["zone"] not in gcp_zones:
                invalid_zones.append((pool.workerPoolId, machine_type, machine["zone"]))
            zone_machine_types = gcp_api.list_machine_types(machine["zone"])
            if machine_type not in zone_machine_types:
                invalid_machine_types.append(
                    (pool.workerPoolId, machine_type, machine["zone"])
                )

    message = "\n".join(
        f" - {pool_id}: {machine_type} (zone: {zone})"
        for pool_id, machine_type, zone in invalid_zones
    )
    assert not invalid_zones, f"Invalid GCP worker zones found: \n{message}"

    message = "\n".join(
        f" - {pool_id}: {machine_type} (zone: {zone})"
        for pool_id, machine_type, zone in invalid_machine_types
    )
    assert not invalid_machine_types, (
        f"Invalid GCP worker machine types found: \n{message}"
    )


# gecko-{1,3,t} pools with no enterprise-* pool. Remove an entry when its
# enterprise pool is added.
GECKO_ONLY_POOL_PATTERNS = (
    r"-alpha$",
    r"relsre",
)
GECKO_ONLY_POOLS = {
    # Not referenced by the worker aliases in enterprise-firefox
    # taskcluster/config.yml.
    "gecko-1/b-linux-2204-kvm-gcp",
    "gecko-1/b-linux-gcp-aarch64",
    "gecko-1/b-win2022-headless",
    "gecko-1/b-win2022-updatebot",
    "gecko-1/b-win2025-core",
    "gecko-1/b-win2025-headless",
    "gecko-1/b-win2025-large",
    "gecko-1/b-win2025-updatebot",
    "gecko-3/b-linux-2204-kvm-gcp",
    "gecko-3/b-linux-gcp-aarch64",
    "gecko-3/b-win2022-headless",
    "gecko-3/b-win2022-updatebot",
    "gecko-3/b-win2025-core",
    "gecko-3/b-win2025-headless",
    "gecko-3/b-win2025-large",
    "gecko-3/b-win2025-updatebot",
    "gecko-t/t-linux-2204-wayland-root-exp",
    "gecko-t/t-linux-2404-wayland",
    "gecko-t/t-linux-docker-large-amd",
    "gecko-t/t-linux-docker-noscratch-large-amd",
    "gecko-t/t-linux-docker-noscratch-nosmt-amd",
    "gecko-t/t-linux-vm-2204-wayland",
    "gecko-t/t-linux-vm-2204-wayland-snap",
    "gecko-t/t-linux-xlarge-2404-wayland",
    "gecko-t/win10-64-2009-webgpu",
    "gecko-t/win11-64-2009",
    "gecko-t/win11-64-2009-source",
    "gecko-t/win11-64-2009-ssd",
    "gecko-t/win11-64-2009-webgpu",
    "gecko-t/win11-64-25h2-amd",
    "gecko-t/win11-64-25h2-bug2078361",
    "gecko-t/win11-64-25h2-ssd",
    "gecko-t/win11-64-25h2-ssd-gpu",
    "gecko-t/win11-64-25h2-unprivileged",
    # Referenced by enterprise-firefox worker aliases, but no enterprise
    # task waits on them now. Add these enterprise pools before enterprise
    # schedules tasks on them.
    "gecko-1/b-linux-docker-updatebot-amd",
    "gecko-1/b-linux-large",
    "gecko-1/b-linux-medium",
    "gecko-1/b-linux-xlarge",
    "gecko-1/b-win2022-xxlarge",
    "gecko-1/b-win2025-xxlarge",
    "gecko-3/b-linux-docker-updatebot-amd",
    "gecko-3/b-linux-large",
    "gecko-3/b-linux-medium",
    "gecko-3/b-linux-xlarge",
    "gecko-3/b-win2022-xxlarge",
    "gecko-3/b-win2025-xxlarge",
    "gecko-t/t-linux-arm64-docker",
    "gecko-t/t-linux-docker-noscratch",
    "gecko-t/win10-64-2009-source",
    "gecko-t/win11-a64-25h2",
}


@pytest.mark.asyncio
async def check_gecko_pools_have_enterprise_pools():
    """Gecko merges into enterprise, so each gecko-{1,3,t} pool needs an
    enterprise-* pool with the same worker type. If not, enterprise tasks
    wait forever (for example #1427 and #1428)."""
    environment = await Environment.current()
    worker_pools = await WorkerPoolConfig.fetch_all()
    pool_ids = {p.pool_id for p in generate_pool_variants(worker_pools, environment)}

    missing = []
    for pool_id in sorted(pool_ids):
        if not re.match(r"gecko-[13t]/", pool_id) or pool_id in GECKO_ONLY_POOLS:
            continue
        if any(re.search(p, pool_id) for p in GECKO_ONLY_POOL_PATTERNS):
            continue
        enterprise_pool_id = "enterprise-" + pool_id.removeprefix("gecko-")
        if enterprise_pool_id not in pool_ids:
            missing.append(f"{pool_id} -> {enterprise_pool_id}")

    stale = sorted(
        pool_id
        for pool_id in GECKO_ONLY_POOLS
        if "enterprise-" + pool_id.removeprefix("gecko-") in pool_ids
        or pool_id not in pool_ids
    )

    if missing:
        print(
            "These gecko pools have no matching enterprise pool. Add the "
            "enterprise-* pool-group, or add the pool to GECKO_ONLY_POOLS:\n"
            + "\n".join(missing)
        )
    if stale:
        print("Remove these stale GECKO_ONLY_POOLS entries:\n" + "\n".join(stale))

    assert not missing and not stale
