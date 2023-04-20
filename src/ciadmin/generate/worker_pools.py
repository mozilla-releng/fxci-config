# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import copy
import hashlib
import pprint

import attr
from tcadmin.resources import WorkerPool

from ..util.keyed_by import evaluate_keyed_by
from ..util.templates import merge
from .ciconfig.environment import Environment
from .ciconfig.get import get_ciconfig_file
from .ciconfig.worker_images import WorkerImage
from .ciconfig.worker_pools import WorkerPool as ConfigWorkerPool


def is_invalid_aws_instance_type(invalid_instances, zone, instance_type):
    family, size = instance_type.split(".", 1)
    return any(
        (zone in entry["zones"]) and (family in entry["families"])
        for entry in invalid_instances
    )


def _validate_instance_capacity(pool_id, implementation, instance_types):
    for instance_type in instance_types:
        if "capacity" in instance_type:
            raise ValueError(
                "To set capacity per instance for an instance type, "
                "set `capacityPerInstance` "
                f"in worker {pool_id}.",
            )
        if "capacity" in instance_type.get("worker-config", {}):
            raise ValueError(
                "To set capacity per instance for an instance type, "
                "set `capacityPerInstance` on the instance type, "
                "rather than the worker config "
                f"in worker {pool_id}.",
            )
        if (
            instance_type.get("capacityPerInstance", 1) != 1
            and implementation != "docker-worker"
        ):
            raise ValueError(
                f"{implementation} does not support capacity-per-instance != 1 "
                f"in worker {pool_id}.",
            )


def _populate_deployment_id(instance_worker_config, image_id):
    if "genericWorker" not in instance_worker_config or instance_worker_config[
        "genericWorker"
    ]["config"].get("deploymentId"):
        return
    _hash_config = copy.deepcopy(instance_worker_config)
    _hash_config["imageId"] = image_id
    instance_worker_config["genericWorker"]["config"]["deploymentId"] = hashlib.sha256(
        pprint.pformat(_hash_config).encode("utf-8")
    ).hexdigest()


def get_aws_provider_config(
    environment, provider_id, pool_id, config, worker_images, defaults
):
    regions = config.pop("regions")
    image = worker_images[config["image"]]
    instance_types = config["instance_types"]
    security = config.pop("security", "untrusted")
    spot = config.pop("spot", True)
    user_data = config.pop("additional-user-data", {})
    implementation = config.pop("implementation", "docker-worker")

    defaults = evaluate_keyed_by(defaults, "defaults", {"provider": provider_id})
    aws_config = environment.aws_config

    lifecycle = merge(defaults.get("lifecycle", {}), config.pop("lifecycle", {}))

    worker_config = evaluate_keyed_by(
        defaults.get("worker-config", {}),
        pool_id,
        {"implementation": implementation},
    )
    worker_config = merge(worker_config, config.get("worker-config", {}))

    _validate_instance_capacity(pool_id, implementation, instance_types)

    launch_configs = []
    for region in regions:
        availability_zones = evaluate_keyed_by(
            aws_config["availability-zones"], pool_id, {"region": region}
        )
        security_groups = evaluate_keyed_by(
            aws_config["security-groups"],
            pool_id,
            {"region": region, "security": security},
        )
        for availability_zone in availability_zones:
            subnet_id = evaluate_keyed_by(
                aws_config["subnet-id"],
                pool_id,
                {"availability-zone": availability_zone},
            )

            for instance_type in instance_types:
                if is_invalid_aws_instance_type(
                    aws_config["invalid-instances"],
                    availability_zone,
                    instance_type["instanceType"],
                ):
                    continue
                if implementation == "docker-worker":
                    instance_worker_config = merge(
                        worker_config,
                        instance_type.get("worker-config", {}),
                        {"capacity": instance_type.get("capacityPerInstance", 1)},
                    )
                else:
                    instance_worker_config = merge(
                        worker_config,
                        instance_type.get("worker-config", {}),
                    )
                    if aws_config.get("wst_server_url") and instance_worker_config.get(
                        "genericWorker", {}
                    ).get("config"):
                        instance_worker_config["genericWorker"]["config"].setdefault(
                            "wstServerURL", aws_config["wst_server_url"]
                        )
                image_id = image.image_id(provider_id, region)
                _populate_deployment_id(instance_worker_config, image_id)
                launch_config = {
                    "capacityPerInstance": instance_type.get("capacityPerInstance", 1),
                    "region": region,
                    "launchConfig": {
                        "ImageId": image_id,
                        "Placement": {"AvailabilityZone": availability_zone},
                        "SubnetId": subnet_id,
                        "SecurityGroupIds": security_groups,
                        "InstanceType": instance_type["instanceType"],
                    },
                    "workerConfig": instance_worker_config,
                }
                launch_config["additionalUserData"] = {}
                launch_config["additionalUserData"].update(user_data)
                launch_config["additionalUserData"].update(
                    instance_type.get("additional-user-data", {})
                )
                launch_config["launchConfig"] = merge(
                    launch_config["launchConfig"], instance_type.get("launchConfig", {})
                )
                if spot:
                    launch_config["launchConfig"]["InstanceMarketOptions"] = {
                        "MarketType": "spot"
                    }
                launch_configs.append(launch_config)

    return {
        "minCapacity": config.get("minCapacity", 0),
        "maxCapacity": config["maxCapacity"],
        "scalingRatio": config.get("scalingRatio", 1),
        "lifecycle": lifecycle,
        "launchConfigs": launch_configs,
    }


def get_azure_provider_config(
    environment, provider_id, pool_id, config, worker_images, defaults
):
    locations = config.pop("locations")
    image_rgroup = config.pop("image_resource_group")
    vmSizes = config["vmSizes"]
    purpose = config["worker-purpose"]
    image = worker_images[config["image"]]
    implementation = config.pop(
        "implementation", "generic-worker/worker-runner-windows"
    )

    defaults = evaluate_keyed_by(defaults, "defaults", {"provider": provider_id})
    azure_config = environment.azure_config

    lifecycle = merge(defaults.get("lifecycle", {}), config.pop("lifecycle", {}))

    worker_config = evaluate_keyed_by(
        defaults.get("worker-config", {}),
        pool_id,
        {"implementation": implementation},
    )
    worker_config = merge(worker_config, config.get("worker-config", {}))
    if azure_config.get("wst_server_url"):
        worker_config["genericWorker"]["config"].setdefault(
            "wstServerURL", azure_config["wst_server_url"]
        )
    tags = config.get("tags", {})
    # Temporary conditional language while we move pools over to the newer
    # method that is in the else clause
    # Refrence https://mozilla-hub.atlassian.net/browse/RELOPS-212
    if config.get("old-style-worker-config"):
        launch_configs = []
        for location in locations:
            for vmSize in vmSizes:
                loc = location.replace("-", "")
                ImageId = image.image_id(provider_id, location)
                subscription_id = azure_config["untrusted_subscription"]
                subscription_id = f"/subscriptions/{subscription_id}"
                resource_suffix = f"{location}-{purpose}"
                rgroup = f"rg-{resource_suffix}"
                vnet = f"vn-{resource_suffix}"
                snet = f"sn-{resource_suffix}"
                subnetId = (
                    f"{subscription_id}/resourceGroups/{rgroup}/providers/"
                    f"Microsoft.Network/virtualNetworks/{vnet}/subnets/{snet}"
                )
                imageReference_id = (
                    f"{subscription_id}/resourceGroups/{image_rgroup}/providers/"
                    f"Microsoft.Compute/images/{ImageId}"
                )
                launch_config = {
                    "location": loc,
                    "subnetId": subnetId,
                    "tags": merge(
                        tags,
                    ),
                    "workerConfig": merge(
                        worker_config,
                    ),
                    "hardwareProfile": {"vmSize": vmSize},
                    "priority": "spot",
                    "billingProfile": {"maxPrice": -1},
                    "evictionPolicy": "Delete",
                    "capacityPerInstance": 1,
                    "storageProfile": {"imageReference": {"id": imageReference_id}},
                }

            launch_config = merge(launch_config, vmSize.get("launchConfig", {}))
            launch_configs.append(launch_config)

        return {
            "minCapacity": config.get("minCapacity", 0),
            "maxCapacity": config["maxCapacity"],
            "scalingRatio": config.get("scalingRatio", 1),
            "lifecycle": lifecycle,
            "launchConfigs": launch_configs,
        }
    else:
        launch_configs = []
        for location in locations:
            for vmSize in vmSizes:
                loc = location.replace("-", "")
                DeploymentId = image.image_id(provider_id, "deployment_id")
                ImageId = image.image_id(provider_id, location)
                if provider_id == "azure_trusted":
                    subscription_id = azure_config["trusted_subscription"]
                else:
                    subscription_id = azure_config["untrusted_subscription"]
                subscription_id = f"/subscriptions/{subscription_id}"
                resource_suffix = f"{location}-{purpose}"
                rgroup = f"rg-{resource_suffix}"
                vnet = f"vn-{resource_suffix}"
                snet = f"sn-{resource_suffix}"
                subnetId = (
                    f"{subscription_id}/resourceGroups/{rgroup}/providers/"
                    f"Microsoft.Network/virtualNetworks/{vnet}/subnets/{snet}"
                )
                imageReference_id = (
                    f"{subscription_id}/resourceGroups/{image_rgroup}/providers/"
                    f"Microsoft.Compute/images/{ImageId}-{DeploymentId}"
                )
                tags["deploymentId"] = DeploymentId

                launch_config = {
                    "location": loc,
                    "subnetId": subnetId,
                    "tags": merge(
                        tags,
                    ),
                    "workerConfig": merge(
                        worker_config,
                    ),
                    "hardwareProfile": {"vmSize": vmSize},
                    "priority": "spot",
                    "billingProfile": {"maxPrice": -1},
                    "evictionPolicy": "Delete",
                    "capacityPerInstance": 1,
                    "storageProfile": {"imageReference": {"id": imageReference_id}},
                }

                launch_config = merge(launch_config, vmSize.get("launchConfig", {}))
                launch_configs.append(launch_config)

        return {
            "minCapacity": config.get("minCapacity", 0),
            "maxCapacity": config["maxCapacity"],
            "scalingRatio": config.get("scalingRatio", 1),
            "lifecycle": lifecycle,
            "launchConfigs": launch_configs,
        }


def get_google_provider_config(
    environment, provider_id, pool_id, config, worker_images, defaults
):
    regions = config.pop("regions")
    image = worker_images[config["image"]]
    instance_types = config["instance_types"]
    implementation = config.pop("implementation", "docker-worker")

    defaults = evaluate_keyed_by(defaults, "defaults", {"provider": provider_id})
    google_config = environment.google_config

    lifecycle = merge(defaults.get("lifecycle", {}), config.pop("lifecycle", {}))

    worker_config = evaluate_keyed_by(
        defaults.get("worker-config", {}),
        pool_id,
        {"implementation": implementation},
    )
    worker_config = merge(worker_config, config.get("worker-config", {}))

    image_name = image.image_id(provider_id)

    _validate_instance_capacity(pool_id, implementation, instance_types)

    launch_configs = []
    for region in regions:
        zones = evaluate_keyed_by(google_config["zones"], pool_id, {"region": region})
        for zone in zones:
            for instance_type in instance_types:
                launch_config = copy.deepcopy(instance_type)
                launch_config.setdefault("capacityPerInstance", 1)
                launch_config.update({"region": region, "zone": zone})

                # When using anchors and aliases, PyYaml re-uses the same
                # object in memory. Make a copy to avoid modifying the same
                # object multiple times.
                launch_config["disks"] = [
                    copy.deepcopy(d) for d in launch_config["disks"]
                ]
                for disk in launch_config["disks"]:
                    if disk["initializeParams"].get("sourceImage") == "<image>":
                        disk["initializeParams"]["sourceImage"] = image_name
                    if disk["initializeParams"].get("diskType"):
                        yamlDefinedDiskType = disk["initializeParams"]["diskType"]
                        disk["initializeParams"]["diskType"] = (
                            "zones/" + zone + "/" + yamlDefinedDiskType
                        )
                launch_config["workerConfig"] = merge(
                    worker_config,
                    launch_config.pop("worker-config", {}),
                )
                if implementation == "docker-worker":
                    launch_config["workerConfig"] = merge(
                        launch_config["workerConfig"],
                        {"capacity": instance_type.get("capacityPerInstance", 1)},
                    )
                else:
                    if google_config.get("wst_server_url") and launch_config[
                        "workerConfig"
                    ].get("genericWorker", {}).get("config"):
                        launch_config["workerConfig"]["genericWorker"][
                            "config"
                        ].setdefault("wstServerURL", google_config["wst_server_url"])
                launch_config[
                    "machineType"
                ] = f"zones/{zone}/machineTypes/{launch_config.pop('machine_type')}"

                for acc in launch_config.get("guestAccelerators", []):
                    acc[
                        "acceleratorType"
                    ] = f"zones/{zone}/acceleratorTypes/{acc['acceleratorType']}"

                # TODO: Add an option for requesting non-prementible instances
                launch_config["scheduling"] = {
                    "onHostMaintenance": "terminate",
                    "automaticRestart": False,
                    "preemptible": True,
                }
                launch_configs.append(launch_config)

    return {
        "minCapacity": config.get("minCapacity", 0),
        "maxCapacity": config["maxCapacity"],
        "scalingRatio": config.get("scalingRatio", 1),
        "lifecycle": lifecycle,
        "launchConfigs": launch_configs,
    }


PROVIDER_IMPLEMENTATIONS = {
    "aws": get_aws_provider_config,
    "google": get_google_provider_config,
    "azure": get_azure_provider_config,
}


async def make_worker_pool(environment, resources, wp, worker_images, worker_defaults):
    if wp.provider_id in environment.worker_manager["providers"]:
        provider_implementation = environment.worker_manager["providers"][
            wp.provider_id
        ]["implementation"]
        config = PROVIDER_IMPLEMENTATIONS[provider_implementation](
            environment,
            wp.provider_id,
            wp.pool_id,
            copy.deepcopy(wp.config),
            worker_images,
            worker_defaults,
        )
    else:
        config = wp.config

    return WorkerPool(
        workerPoolId=wp.pool_id,
        description=wp.description,
        owner=wp.owner,
        providerId=wp.provider_id,
        config=config,
        emailOnError=wp.email_on_error,
    )


def generate_pool_variants(worker_pools, environment):
    """
    Generate the list of worker pools by evaluting them at all the specified
    variants.
    """

    def update_config(config, name, attributes):
        config = copy.deepcopy(config)
        for key in [
            "image",
            "maxCapacity",
            "minCapacity",
            "security",
            "instance_types",
        ]:
            if key in config:
                value = evaluate_keyed_by(config[key], name, attributes)
                if value is not None:
                    config[key] = value
                else:
                    del config[key]
        return config

    for wp in worker_pools:
        for variant in wp.variants:
            name = wp.pool_id.format(**variant)
            attributes = {"environment": environment}
            attributes.update(variant)

            yield attr.evolve(
                wp,
                pool_id=name,
                provider_id=evaluate_keyed_by(wp.provider_id, name, attributes),
                config=update_config(wp.config, name, attributes),
                variants=[{}],
            )


async def update_resources(resources):
    """
    Manage the worker-pool configurations
    """
    worker_pools = await ConfigWorkerPool.fetch_all()
    worker_images = await WorkerImage.fetch_all()

    resources.manage("WorkerPool=.*")

    worker_defaults = (await get_ciconfig_file("worker-pools.yml")).get(
        "worker-defaults"
    )
    environment = await Environment.current()

    for wp in generate_pool_variants(worker_pools, environment):
        apwt = await make_worker_pool(
            environment, resources, wp, worker_images, worker_defaults
        )
        if apwt:
            resources.add(apwt)
