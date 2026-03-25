#!/usr/bin/env python3
"""Generate Taskcluster resources from flat config/pools.yml.

Reads config/pools.yml + config/environments.yml + config/images.yml,
applies cascading defaults, expands regions x zones x instance_types
into full Taskcluster launch configs, and outputs JSON.
"""

import copy
import json
import os
import sys

import yaml

DESCRIPTION_PREFIX = (
    "*DO NOT EDIT* - This resource is configured automatically by "
    "[ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
)

# Default docker-worker workerConfig (keys in alphabetical order for stable output)
DEFAULT_DW_WORKER_CONFIG = {
    "artifacts": {
        "skipCompressionExtensions": [
            ".7z", ".bz2", ".deb", ".dmg", ".flv", ".gif", ".gz",
            ".jpeg", ".jpg", ".png", ".swf", ".tbz", ".tgz",
            ".webp", ".whl", ".woff", ".woff2", ".xz", ".zip",
            ".zst", "lz4",
        ]
    },
    "capacity": 1,
    "deviceManagement": {
        "hostSharedMemory": {"enabled": False},
        "kvm": {"enabled": False},
    },
    "shutdown": {"afterIdleSeconds": 120, "enabled": True},
}


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def deep_merge(base, override):
    """Merge override into base. Dicts merge recursively, else replaced."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ── Image resolution ──────────────────────────────────────────────────

def build_image_index(images_path):
    """Build image_name -> {provider: full_path} index, resolving aliases."""
    raw = load_yaml(images_path)
    resolved = {}

    def resolve(name):
        visited = set()
        while isinstance(raw.get(name), str):
            if name in visited:
                break
            visited.add(name)
            name = raw[name]
        return name, raw.get(name, {})

    for name in raw:
        canonical, cloud_map = resolve(name)
        if isinstance(cloud_map, dict):
            resolved[name] = cloud_map
    return resolved


def resolve_image(image_name, provider_id, image_index):
    """Resolve an image name to a full path for a given provider."""
    if image_name.startswith("projects/"):
        return image_name  # already a full path
    cloud_map = image_index.get(image_name, {})
    if isinstance(cloud_map, dict) and provider_id in cloud_map:
        path = cloud_map[provider_id]
        if isinstance(path, str):
            return path
    raise ValueError(f"Cannot resolve image '{image_name}' for provider '{provider_id}'")


# ── Disk shorthand parsing ────────────────────────────────────────────

def parse_disks(shorthand):
    """Parse disk shorthand like 'boot-75gb+ssd+ssd' into disk definitions."""
    disks = []
    for part in shorthand.split("+"):
        if part.startswith("boot-"):
            size = int(part.replace("boot-", "").replace("gb", ""))
            disks.append({
                "type": "PERSISTENT",
                "size_gb": size,
                "boot": True,
                "auto_delete": True,
            })
        elif part == "ssd":
            disks.append({
                "type": "SCRATCH",
                "disk_type": "local-ssd",
                "auto_delete": True,
                "interface": "NVME",
            })
        else:
            raise ValueError(f"Unknown disk shorthand: {part}")
    return disks


# ── GCP expansion ─────────────────────────────────────────────────────

def is_invalid_gcp_instance(invalid_instances, zone, machine_type):
    family = machine_type.split("-")[0]
    return any(
        zone in entry["zones"] and family in entry["families"]
        for entry in invalid_instances
    )


def expand_gcp_pool(pool, env, defaults, image_index):
    google = env["google"]
    zones_by_region = google["zones"]
    invalid_instances = google.get("invalid_instances", [])
    wst_url = google.get("wst_server_url")

    regions = pool.get("regions", defaults.get("regions", []))
    implementation = pool.get("implementation", defaults.get("implementation", "docker-worker"))
    scheduling_type = pool.get("scheduling", "spot")
    image_name = pool["image"]
    image_path = resolve_image(image_name, pool["provider_id"], image_index)

    scheduling_options = {
        "spot": {
            "instanceTerminationAction": "DELETE",
            "onHostMaintenance": "terminate",
            "provisioningModel": "SPOT",
        },
        "standard": {
            "onHostMaintenance": "terminate",
            "provisioningModel": "STANDARD",
        },
    }

    # Build base workerConfig
    if implementation == "docker-worker":
        base_wc = copy.deepcopy(DEFAULT_DW_WORKER_CONFIG)
    else:
        base_wc = {}
    base_wc = deep_merge(base_wc, pool.get("worker_config", {}))

    # Build instance types list
    if "instance_types" in pool:
        instance_types = pool["instance_types"]
    else:
        instance_types = [{
            "machine_type": pool["machine_type"],
            "disks": pool["disks"],
        }]
        if pool.get("capacity_per_instance"):
            instance_types[0]["capacity_per_instance"] = pool["capacity_per_instance"]
        if pool.get("advanced_machine_features"):
            instance_types[0]["advanced_machine_features"] = pool["advanced_machine_features"]
        if pool.get("guest_accelerators"):
            instance_types[0]["guest_accelerators"] = pool["guest_accelerators"]

    launch_configs = []
    for region in regions:
        zones = zones_by_region.get(region, [])
        for zone in zones:
            for it in instance_types:
                machine_type = it["machine_type"]
                if is_invalid_gcp_instance(invalid_instances, zone, machine_type):
                    continue

                cpi = it.get("capacity_per_instance", 1)

                # Parse disk shorthand if string
                disk_defs = parse_disks(it["disks"]) if isinstance(it["disks"], str) else it["disks"]

                # Build disks
                disks = []
                for dd in disk_defs:
                    disk = {"autoDelete": True}
                    if dd.get("boot"):
                        disk["boot"] = True
                    ip = {}
                    if dd.get("size_gb"):
                        ip["diskSizeGb"] = dd["size_gb"]
                    if dd.get("boot") and image_path:
                        ip["sourceImage"] = image_path
                    if dd.get("disk_type"):
                        ip["diskType"] = f"zones/{zone}/diskTypes/{dd['disk_type']}"
                    disk["initializeParams"] = ip
                    if dd.get("interface"):
                        disk["interface"] = dd["interface"]
                    disk["type"] = dd["type"]
                    disks.append(disk)

                # Build workerConfig
                lc_wc = copy.deepcopy(base_wc)
                if implementation == "docker-worker":
                    lc_wc["capacity"] = cpi
                elif implementation == "generic-worker" and wst_url:
                    if "genericWorker" in lc_wc and "config" in lc_wc["genericWorker"]:
                        lc_wc["genericWorker"]["config"].setdefault("wstServerURL", wst_url)

                lc = {
                    "capacityPerInstance": cpi,
                    "disks": disks,
                    "machineType": f"zones/{zone}/machineTypes/{machine_type}",
                    "networkInterfaces": [{"accessConfigs": [{"type": "ONE_TO_ONE_NAT"}]}],
                    "region": region,
                    "scheduling": scheduling_options[scheduling_type],
                    "workerConfig": lc_wc,
                    "zone": zone,
                }

                # min_cpu_platform: pool-level overrides default; None means omit
                mcp = pool.get("min_cpu_platform", defaults.get("min_cpu_platform"))
                if mcp is not None:
                    lc["minCpuPlatform"] = mcp

                if it.get("advanced_machine_features"):
                    lc["advancedMachineFeatures"] = it["advanced_machine_features"]

                if it.get("guest_accelerators"):
                    lc["guestAccelerators"] = [
                        {
                            "acceleratorCount": acc["count"],
                            "acceleratorType": f"zones/{zone}/acceleratorTypes/{acc['type']}",
                        }
                        for acc in it["guest_accelerators"]
                    ]

                launch_configs.append(lc)

    description = pool.get("description", defaults.get("description", ""))
    if not description.startswith(DESCRIPTION_PREFIX):
        description = DESCRIPTION_PREFIX + description

    return {
        "config": {
            "launchConfigs": launch_configs,
            "lifecycle": defaults.get("lifecycle", {}),
            "maxCapacity": pool["max_capacity"],
            "minCapacity": pool.get("min_capacity", 0),
            "scalingRatio": defaults.get("scaling_ratio", 1),
        },
        "description": description,
        "emailOnError": pool.get("email_on_error", defaults.get("email_on_error", True)),
        "owner": pool.get("owner", defaults.get("owner", "")),
        "providerId": pool["provider_id"],
        "workerPoolId": pool["id"],
    }


# ── Azure expansion ───────────────────────────────────────────────────

AZURE_LOC_TO_NOHYPHEN = {
    "central-us": "centralus",
    "east-us": "eastus",
    "eastus": "eastus",
    "east-us-2": "eastus2",
    "north-central-us": "northcentralus",
    "north-europe": "northeurope",
    "south-central-us": "southcentralus",
    "west-us": "westus",
    "west-us-2": "westus2",
    "west-us-3": "westus3",
    "west-europe": "westeurope",
    "uk-south": "uksouth",
    "uk-west": "ukwest",
    "canada-central": "canadacentral",
    "central-india": "centralindia",
    "south-india": "southindia",
}


def expand_azure_pool(pool, env, defaults):
    azure = env["azure"]
    wst_url = azure.get("wst_server_url")

    provider_id = pool["provider_id"]
    subscription_id = azure["trusted_subscription"] if provider_id == "azure_trusted" else azure["untrusted_subscription"]
    sub_prefix = f"/subscriptions/{subscription_id}"

    locations = pool["locations"]
    vm_sizes = pool["vm_sizes"]
    image_info = pool["image"]
    tags = pool.get("tags", {})
    worker_purpose = pool.get("worker_purpose", pool["id"].split("/")[0])

    base_wc = copy.deepcopy(pool.get("worker_config", {}))
    if wst_url and "genericWorker" in base_wc and "config" in base_wc["genericWorker"]:
        base_wc["genericWorker"]["config"].setdefault("wstServerURL", wst_url)

    os_profile = pool.get("os_profile")
    diag_profile = pool.get("diagnostics_profile")
    data_disks = pool.get("data_disks")
    os_disk = pool.get("os_disk")

    launch_configs = []
    for location in locations:
        loc_nohyphen = AZURE_LOC_TO_NOHYPHEN.get(location, location.replace("-", ""))
        resource_suffix = f"{location}-{worker_purpose}"
        subnet_id = (
            f"{sub_prefix}/resourceGroups/rg-{resource_suffix}/providers/"
            f"Microsoft.Network/virtualNetworks/vn-{resource_suffix}/subnets/sn-{resource_suffix}"
        )

        if image_info["type"] == "gallery":
            image_ref_id = (
                f"{sub_prefix}/resourceGroups/{image_info['resource_group']}/providers/"
                f"Microsoft.Compute/galleries/{image_info['gallery']}/images/{image_info['image']}/versions/{image_info['version']}"
            )
        elif image_info["type"] == "location":
            overrides = image_info.get("location_overrides", {})
            if location in overrides:
                full_name = overrides[location]
            else:
                full_name = f"{image_info['name_prefix']}-{loc_nohyphen}-{image_info['os_sku']}-{image_info['deployment_id']}"
            image_ref_id = (
                f"{sub_prefix}/resourceGroups/{image_info['resource_group']}/providers/"
                f"Microsoft.Compute/images/{full_name}"
            )
        else:
            image_ref_id = image_info["full_name_template"]

        lc_tags = copy.deepcopy(tags)
        if image_info.get("deployment_id"):
            lc_tags["deploymentId"] = image_info["deployment_id"]

        for vm_size in vm_sizes:
            lc = {
                "billingProfile": {"maxPrice": -1},
                "capacityPerInstance": 1,
                "evictionPolicy": "Delete",
                "hardwareProfile": {"vmSize": vm_size},
                "location": loc_nohyphen,
                "priority": "spot",
                "storageProfile": {"imageReference": {"id": image_ref_id}},
                "subnetId": subnet_id,
                "tags": copy.deepcopy(lc_tags),
                "workerConfig": copy.deepcopy(base_wc),
            }

            if diag_profile:
                lc["diagnosticsProfile"] = copy.deepcopy(diag_profile)
            if os_profile:
                lc["osProfile"] = copy.deepcopy(os_profile)
            if data_disks:
                lc["storageProfile"]["dataDisks"] = copy.deepcopy(data_disks)
            if os_disk:
                lc["storageProfile"]["osDisk"] = copy.deepcopy(os_disk)

            launch_configs.append(lc)

    description = pool.get("description", defaults.get("description", ""))
    if not description.startswith(DESCRIPTION_PREFIX):
        description = DESCRIPTION_PREFIX + description

    return {
        "config": {
            "launchConfigs": launch_configs,
            "lifecycle": defaults.get("lifecycle", {}),
            "maxCapacity": pool["max_capacity"],
            "minCapacity": pool.get("min_capacity", 0),
            "scalingRatio": defaults.get("scaling_ratio", 1),
        },
        "description": description,
        "emailOnError": pool.get("email_on_error", defaults.get("email_on_error", True)),
        "owner": pool.get("owner", defaults.get("owner", "")),
        "providerId": pool["provider_id"],
        "workerPoolId": pool["id"],
    }


# ── Main ──────────────────────────────────────────────────────────────

def apply_template(pool, templates):
    """Merge template fields into pool (pool fields take precedence)."""
    tmpl_name = pool.get("template")
    if not tmpl_name or not templates:
        return pool
    tmpl = templates.get(tmpl_name)
    if not tmpl:
        raise ValueError(f"Unknown template '{tmpl_name}' for pool {pool['id']}")
    # Template fields are defaults — pool fields override
    merged = copy.deepcopy(tmpl)
    merged.update(pool)
    del merged["template"]
    return merged


def generate_worker_pools(config, env, image_index):
    defaults = config["defaults"]
    templates = config.get("templates", {})
    providers = env["providers"]
    results = []

    for pool in config["pools"]:
        pool = apply_template(pool, templates)
        impl = providers.get(pool["provider_id"], {}).get("implementation", "")
        if impl == "google":
            results.append(expand_gcp_pool(pool, env, defaults, image_index))
        elif impl == "azure":
            results.append(expand_azure_pool(pool, env, defaults))
        else:
            print(f"WARNING: unknown provider impl {impl} for {pool['id']}", file=sys.stderr)

    results.sort(key=lambda p: p["workerPoolId"])
    return results


def main():
    config = load_yaml("config/pools.yml")
    env = load_yaml("config/environments.yml")["firefoxci"]
    image_index = build_image_index("config/images.yml")

    worker_pools = generate_worker_pools(config, env, image_index)

    os.makedirs("output", exist_ok=True)
    with open("output/workerpools.json", "w") as f:
        json.dump(worker_pools, f, indent=2, sort_keys=True)

    print(f"Generated {len(worker_pools)} worker pools")


if __name__ == "__main__":
    main()
