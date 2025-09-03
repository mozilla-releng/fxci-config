# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import re
from textwrap import dedent

import pytest
from google.cloud.compute import ListMachineTypesRequest, MachineTypesClient
from google.oauth2 import service_account
from tcadmin.resources import Resources

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_images import WorkerImage
from ciadmin.generate.ciconfig.worker_pools import WorkerPool as WorkerPoolConfig
from ciadmin.generate.worker_pools import generate_pool_variants, make_worker_pool

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
async def check_worker_pool_tags():
    invalid_pools = set()

    environment = await Environment.current()
    resources = Resources()
    worker_pools = await WorkerPoolConfig.fetch_all()
    worker_images = await WorkerImage.fetch_all()
    for pool in generate_pool_variants(worker_pools, environment):
        pool = await make_worker_pool(environment, resources, pool, worker_images, {})
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


GCP_MACHINE_TYPE_REGEX = re.compile(
    r"""
    ^(?P<machine_series>[^-]+)
    -(?P<machine_configuration>[^-]+)
    -(?P<number_of_cpus>\d+)
    (-(?P<suffix>.+))?
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
    if machine_series not in ("n1", "n2", "n2d", "c2", "c2d", "c3d", "c4d", "t2a"):
        raise NotImplementedError(
            f"Min scratch disks not implemented for '{machine_type}'"
        )

    # t2a ARM64 machines don't support Local SSD disks.
    if machine_series == "t2a":
        return 0

    if machine_series == "n1":
        return 1

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
            min_disks = min_scratch_disks(instance["machine_type"])

            if not num_disks:
                continue
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


@pytest.mark.asyncio
async def check_worker_pool_gcp_instances_by_region():
    gcp_token = os.getenv("GCP_CHECK_TOKEN", None)
    if not gcp_token:
        return pytest.skip("GCP_CHECK_TOKEN not set")

    # Fetch GCP pools
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(gcp_token)
    )
    gcp_api_client = MachineTypesClient(credentials=credentials)

    environment = await Environment.current()
    resources = Resources()
    worker_pools = await WorkerPoolConfig.fetch_all()
    worker_images = await WorkerImage.fetch_all()

    generated_pools = []
    zones = set()
    # Generate the pools
    for pool in generate_pool_variants(worker_pools, environment):
        if "gcp" not in pool.provider_id:
            continue
        generated = await make_worker_pool(
            environment, resources, pool, worker_images, {}
        )
        generated_pools.append(generated)
        # Collect zones to query GCP
        for machine in generated.config["launchConfigs"]:
            if "custom" in machine["machineType"].split("/")[-1]:
                continue  # Skip custom machine types
            zones.add(machine["zone"])

    gcp_zone_machine_types = {}
    for zone in zones:
        for record in gcp_api_client.list(
            ListMachineTypesRequest(project=credentials.project_id, zone=zone)
        ):
            # Machine type == record.name
            gcp_zone_machine_types.setdefault(zone, set()).add(record.name)

    invalid_pools = []
    for pool in generated_pools:
        for machine in pool.config["launchConfigs"]:
            machine_type = machine["machineType"].split("/")[-1]
            if "custom" in machine_type:
                continue
            if machine_type not in gcp_zone_machine_types[machine["zone"]]:
                invalid_pools.append((pool.id, machine_type, machine["zone"]))

    message = "\n".join(
        f" - {pool_id}: {machine_type} (zone: {zone})"
        for pool_id, machine_type, zone in invalid_pools
    )
    assert not invalid_pools, f"Invalid GCP worker pools found: \n{message}"
