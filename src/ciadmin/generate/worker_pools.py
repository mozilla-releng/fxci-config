# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import copy
import hashlib
import json
import pprint

import attr
from tcadmin.resources import WorkerPool

from ..util.keyed_by import evaluate_keyed_by, iter_dot_path, resolve_keyed_by
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


def is_invalid_gcp_instance_type(invalid_instances, zone, machine_type):
    # Parse machine type: family-profile-cpus[-suffix]
    # e.g., "c4d-standard-8-lssd" -> family="c4d", suffix="lssd"
    parts = machine_type.split("-")
    family = parts[0]
    profile = parts[1]
    # Suffix will be anything after cpus number
    if len(parts) < 3:
        # Wrong machine type
        raise Exception(
            f"Machine type should be on the format <family>-<profile>-<cpus>[-<suffix>]. Got: {machine_type}"
        )
    elif len(parts) == 3:
        # No suffix
        suffix = None
    else:
        # Has suffix
        # Note: we might eventually want to support multi suffixes (ie: highlssd-metal)
        #  where a config with -metal is also filtered out
        suffix = "-".join(parts[3:])

    for entry in invalid_instances:
        # Zones and Families are required and always needs to be a match. Suffixes are optional.

        # True if suffixes undefined, or [], or actually matches config
        matches_suffix = not entry.get("suffixes") or suffix in entry["suffixes"]
        matches_profile = not entry.get("profiles") or profile in entry["profiles"]

        if (
            zone in entry["zones"]
            and family in entry["families"]
            and matches_suffix
            and matches_profile
        ):
            # Invalid!
            return True
    # No matches found, machine_type is valid in this zone
    return False


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


def _populate_launch_config_id(launch_config, pool_id):
    launch_config_id = launch_config.get("workerManager", {}).get("launchConfigId")
    if launch_config_id is not None:
        return
    hashedLaunchConfig = hashlib.sha256(
        (pool_id + json.dumps(launch_config, sort_keys=True)).encode("utf8")
    ).hexdigest()
    launch_config.setdefault("workerManager", {})["launchConfigId"] = (
        "lc-" + hashedLaunchConfig[:20]
    )


def _resolve_defaults(defaults, provider_id, implementation):
    keys = (
        "lifecycle",
        "lifecycle.queueInactivityTimeout",
        "lifecycle.registrationTimeout",
        "lifecycle.reregistrationTimeout",
        "worker-config",
    )
    for key in keys:
        resolve_keyed_by(
            defaults,
            key,
            "worker-defaults",
            implementation=implementation,
            provider=provider_id,
        )
    return defaults


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

    aws_config = environment.aws_config

    # Merge defaults with pool config.
    defaults = _resolve_defaults(defaults, provider_id, implementation)
    lifecycle = merge(defaults.get("lifecycle", {}), config.pop("lifecycle", {}))
    worker_config = merge(
        defaults.get("worker-config", {}), config.get("worker-config", {})
    )
    worker_manager_config = merge(
        defaults.get("worker-manager-config", {}),
        config.get("worker-manager-config", {}),
    )

    _validate_instance_capacity(pool_id, implementation, instance_types)

    launch_configs = []
    for region in sorted(regions):
        availability_zones = evaluate_keyed_by(
            aws_config["availability-zones"], pool_id, {"region": region}
        )
        security_groups = evaluate_keyed_by(
            aws_config["security-groups"],
            pool_id,
            {"region": region, "security": security},
        )
        for availability_zone in sorted(availability_zones):
            subnet_id = evaluate_keyed_by(
                aws_config["subnet-id"],
                pool_id,
                {"availability-zone": availability_zone},
            )

            for instance_type in sorted(instance_types):
                if is_invalid_aws_instance_type(
                    aws_config["invalid-instances"],
                    availability_zone,
                    instance_type["instanceType"],
                ):
                    continue

                attrs = {
                    "availabilityZone": availability_zone,
                    "instanceType": instance_type["instanceType"],
                }
                initial_weight = evaluate_keyed_by(
                    worker_manager_config.get("initialWeight", None),
                    "initialWeight",
                    attrs,
                )
                max_capacity = evaluate_keyed_by(
                    worker_manager_config.get("maxCapacity", None),
                    "maxCapacity",
                    attrs,
                )
                instance_worker_manager_config = merge(
                    {
                        "capacityPerInstance": instance_type.get(
                            "capacityPerInstance", 1
                        )
                    },
                    worker_manager_config,
                    (
                        {"initialWeight": initial_weight}
                        if initial_weight is not None
                        else {}
                    ),
                    {"maxCapacity": max_capacity} if max_capacity is not None else {},
                    instance_type.get("worker-manager-config", {}),
                )
                if implementation == "docker-worker":
                    instance_worker_config = merge(
                        worker_config,
                        instance_type.get("worker-config", {}),
                        {
                            "capacity": instance_worker_manager_config.get(
                                "capacityPerInstance", 1
                            )
                        },
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
                image_id = image.get(provider_id, region)
                _populate_deployment_id(instance_worker_config, image_id)
                launch_config = {
                    "region": region,
                    "launchConfig": {
                        "ImageId": image_id,
                        "Placement": {"AvailabilityZone": availability_zone},
                        "SubnetId": subnet_id,
                        "SecurityGroupIds": security_groups,
                        "InstanceType": instance_type["instanceType"],
                    },
                    "workerConfig": instance_worker_config,
                    "workerManager": instance_worker_manager_config,
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
                launch_config["launchConfig"].pop("capacityPerInstance", None)
                _populate_launch_config_id(launch_config, pool_id)
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
    vmSizes = config["vmSizes"]
    purpose = config.get("worker-purpose") or pool_id.split("/")[0]
    image = worker_images[config["image"]]
    implementation = config.pop(
        "implementation", "generic-worker/worker-runner-windows"
    )
    azure_config = environment.azure_config

    # Merge defaults with pool config.
    defaults = _resolve_defaults(defaults, provider_id, implementation)
    lifecycle = merge(defaults.get("lifecycle", {}), config.pop("lifecycle", {}))
    worker_config = merge(
        defaults.get("worker-config", {}), config.get("worker-config", {})
    )
    worker_manager_config = merge(
        defaults.get("worker-manager-config", {}),
        config.get("worker-manager-config", {}),
    )

    gw_config = worker_config["genericWorker"]["config"]
    if azure_config.get("wst_server_url"):
        gw_config.setdefault("wstServerURL", azure_config["wst_server_url"])

    # Populate some generic-worker metadata.
    metadata = {}
    has_sbom = image.get(provider_id, "sbom") in (None, True)  # defaults None to True
    if has_sbom and "sbom_url_tmpl" in azure_config:
        context = image.clouds[provider_id].copy()

        # The SBOM urls use dashes in the name, whereas the names defined in
        # worker-images.yml can use underscores. This can be removed if these
        # two places ever use the same format.
        if "name" in context:
            context["name"] = context["name"].replace("_", "-")

        metadata["sbom"] = azure_config["sbom_url_tmpl"].format(**context)

    if metadata:
        gw_config.setdefault("workerTypeMetaData", {}).update(metadata)

    tags = config.get("tags", {})

    launch_configs = []
    for location in sorted(locations):
        for vmSize in vmSizes:
            if provider_id == "azure_trusted":
                subscription_id = azure_config["trusted_subscription"]
            else:
                subscription_id = azure_config["untrusted_subscription"]
            loc = location.replace("-", "")
            version = image.get(provider_id, "version")
            image_rgroup = image.get(provider_id, "resource_group")
            DeploymentId = image.get(provider_id, "deployment_id")
            subscription_id = f"/subscriptions/{subscription_id}"
            resource_suffix = f"{location}-{purpose}"
            rgroup = f"rg-{resource_suffix}"
            vnet = f"vn-{resource_suffix}"
            snet = f"sn-{resource_suffix}"
            subnetId = (
                f"{subscription_id}/resourceGroups/{rgroup}/providers/"
                f"Microsoft.Network/virtualNetworks/{vnet}/subnets/{snet}"
            )
            if version != "NA":
                ImageId = image.get(provider_id, "name")
                imageReference_id = (
                    f"{subscription_id}/resourceGroups/{image_rgroup}/providers/"
                    f"Microsoft.Compute/galleries/{ImageId}/images/{ImageId}/versions/{version}"
                )
            else:
                ImageId = image.get(provider_id, location)
                imageReference_id = (
                    f"{subscription_id}/resourceGroups/{image_rgroup}/providers/"
                    f"Microsoft.Compute/images/{ImageId}-{DeploymentId}"
                )
            tags["deploymentId"] = DeploymentId

            attrs = {
                "location": location,
                "vmSize": vmSize.get("vmSize"),
                "pool-id": pool_id,
            }
            initial_weight = evaluate_keyed_by(
                worker_manager_config.get("initialWeight", None), "initialWeight", attrs
            )
            max_capacity = evaluate_keyed_by(
                worker_manager_config.get("maxCapacity", None),
                "maxCapacity",
                attrs,
            )

            # Get publicIp from worker_manager_config or config, if defined
            public_ip_source = None
            if "publicIp" in worker_manager_config:
                public_ip_source = worker_manager_config["publicIp"]
            elif "publicIp" in config:
                public_ip_source = config["publicIp"]

            public_ip = None
            if public_ip_source is not None:
                public_ip = evaluate_keyed_by(
                    public_ip_source,
                    "publicIp",
                    attrs,
                )

            instance_worker_manager_config = merge(
                {"capacityPerInstance": vmSize.get("capacityPerInstance", 1)},
                worker_manager_config,
                {"initialWeight": initial_weight} if initial_weight is not None else {},
                {"maxCapacity": max_capacity} if max_capacity is not None else {},
                {"publicIp": public_ip} if public_ip is not None else {},
                vmSize.get("worker-manager-config", {}),
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
                "storageProfile": {"imageReference": {"id": imageReference_id}},
                "workerManager": instance_worker_manager_config,
            }

            launch_config = merge(launch_config, vmSize.get("launchConfig", {}))
            _populate_launch_config_id(launch_config, pool_id)
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
    google_config = environment.google_config

    # Merge defaults with pool config.
    defaults = _resolve_defaults(defaults, provider_id, implementation)
    lifecycle = merge(defaults.get("lifecycle", {}), config.pop("lifecycle", {}))
    worker_config = merge(
        defaults.get("worker-config", {}), config.get("worker-config", {})
    )
    worker_manager_config = merge(
        defaults.get("worker-manager-config", {}),
        config.get("worker-manager-config", {}),
    )

    image_name = image.get(provider_id)

    _validate_instance_capacity(pool_id, implementation, instance_types)

    launch_configs = []
    for region in sorted(regions):
        zones = evaluate_keyed_by(google_config["zones"], pool_id, {"region": region})
        for zone in sorted(zones):
            for instance_type in instance_types:
                if google_config.get(
                    "invalid-instances"
                ) and is_invalid_gcp_instance_type(
                    google_config["invalid-instances"],
                    zone,
                    instance_type["machine_type"],
                ):
                    continue
                launch_config = copy.deepcopy(instance_type)

                attrs = {
                    "region": region,
                    "zone": zone,
                    "machineType": instance_type["machine_type"],
                }
                initial_weight = evaluate_keyed_by(
                    worker_manager_config.get("initialWeight", None),
                    "initialWeight",
                    attrs,
                )
                max_capacity = evaluate_keyed_by(
                    worker_manager_config.get("maxCapacity", None),
                    "maxCapacity",
                    attrs,
                )
                instance_worker_manager_config = merge(
                    {
                        "capacityPerInstance": launch_config.pop(
                            "capacityPerInstance", 1
                        )
                    },
                    worker_manager_config,
                    (
                        {"initialWeight": initial_weight}
                        if initial_weight is not None
                        else {}
                    ),
                    {"maxCapacity": max_capacity} if max_capacity is not None else {},
                    launch_config.pop("worker-manager-config", {}),
                )
                launch_config["workerManager"] = instance_worker_manager_config
                launch_config.setdefault(
                    "networkInterfaces",
                    [{"accessConfigs": [{"type": "ONE_TO_ONE_NAT"}]}],
                )
                launch_config.update({"region": region, "zone": zone})

                # When using anchors and aliases, PyYaml re-uses the same
                # object in memory. Make a copy to avoid modifying the same
                # object multiple times.
                launch_config["disks"] = [
                    copy.deepcopy(d) for d in launch_config["disks"]
                ]
                for disk in launch_config["disks"]:
                    if "diskSizeGb" in disk:
                        disk["initializeParams"]["diskSizeGb"] = disk.pop("diskSizeGb")
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
                        {
                            "capacity": instance_worker_manager_config.get(
                                "capacityPerInstance", 1
                            )
                        },
                    )
                else:
                    if google_config.get("wst_server_url") and launch_config[
                        "workerConfig"
                    ].get("genericWorker", {}).get("config"):
                        launch_config["workerConfig"]["genericWorker"][
                            "config"
                        ].setdefault("wstServerURL", google_config["wst_server_url"])
                launch_config["machineType"] = (
                    f"zones/{zone}/machineTypes/{launch_config.pop('machine_type')}"
                )

                for acc in launch_config.get("guestAccelerators", []):
                    acc["acceleratorType"] = (
                        f"zones/{zone}/acceleratorTypes/{acc['acceleratorType']}"
                    )

                scheduling_options = {
                    "preemptible": {
                        "onHostMaintenance": "terminate",
                        "automaticRestart": False,
                        "preemptible": True,
                    },
                    "spot": {
                        "onHostMaintenance": "terminate",
                        "provisioningModel": "SPOT",
                        "instanceTerminationAction": "DELETE",
                    },
                    "standard": {
                        "onHostMaintenance": "terminate",
                        "provisioningModel": "STANDARD",
                    },
                }
                scheduling_choice = launch_config.get("scheduling", "spot")
                launch_config["scheduling"] = scheduling_options[scheduling_choice]

                _populate_launch_config_id(launch_config, pool_id)
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
        for key in (
            "image",
            "instance_types",
            "locations",
            "maxCapacity",
            "minCapacity",
            "security",
            "tags.sourceBranch",
            "vmSizes.vmSize",
            "vmSizes.launchConfig.hardwareProfile.vmSize",
            "vmSizes.launchConfig.storageProfile.osDisk.diffDiskSettings.option",
            "worker-purpose",
        ):
            for container, subkey in iter_dot_path(config, key):
                value = evaluate_keyed_by(container[subkey], name, attributes)
                if value is not None:
                    container[subkey] = value
                else:
                    del container[subkey]

        if (
            config.get("worker-config", {})
            .get("shutdown", {})
            .get("afterIdleSeconds", None)
        ):
            value = evaluate_keyed_by(
                config["worker-config"]["shutdown"]["afterIdleSeconds"],
                "worker-config.shutdown.afterIdleSeconds",
                attributes,
            )
            if value is not None:
                config["worker-config"]["shutdown"]["afterIdleSeconds"] = value
            else:
                del config["worker-config"]["shutdown"]["afterIdleSeconds"]

        if config.get("worker-manager-config", {}).get("launchConfigId", None):
            value = evaluate_keyed_by(
                config["worker-manager-config"]["launchConfigId"],
                "worker-manager-config.launchConfigId",
                attributes,
            )
            if value is not None:
                config["worker-manager-config"]["launchConfigId"] = value
            else:
                del config["worker-manager-config"]["launchConfigId"]

        if attributes.get("instance_types", None) and not config.get(
            "instance_types", None
        ):
            config["instance_types"] = attributes["instance_types"]

        for key in (
            "image",
            "implementation",
            "worker-purpose",
            "instance_types.machine_type",
            "worker-config.genericWorker.config.workerType",
            "worker-config.genericWorker.config.provisionerId",
        ):
            for container, subkey in iter_dot_path(config, key):
                container[subkey] = container[subkey].format(**attributes)
                # Some pools append a suffix to the value. Strip "-" for cases
                # where the suffix was empty.
                container[subkey] = container[subkey].rstrip("-_")

        return config

    for wp in worker_pools:
        for variant in wp.variants:
            attributes = wp.attributes.copy()
            attributes["environment"] = environment
            attributes.update(variant)

            name = wp.pool_id.format(**attributes)
            # Some pools append a suffix to the name. Strip "-" for cases where
            # the suffix was empty.
            name = name.rstrip("-")

            yield attr.evolve(
                wp,
                pool_id=name,
                provider_id=evaluate_keyed_by(wp.provider_id, name, attributes),
                config=update_config(wp.config, name, attributes),
                attributes={},
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
            environment, resources, wp, worker_images, copy.deepcopy(worker_defaults)
        )
        if apwt:
            resources.add(apwt)
