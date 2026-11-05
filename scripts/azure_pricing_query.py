#!/usr/bin/env python3

import copy
import functools
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import yaml

from ciadmin.util.keyed_by import resolve_keyed_by

# TODO: Load list of locations from environments.yml
LOCATIONS = [
    "canadacentral",
    "centralus",
    "centralindia",
    "southindia",
    "eastus",
    "eastus2",
    "northcentralus",
    "northeurope",
    "southcentralus",
    "uksouth",
    "westus",
    "westus2",
    "westus3",
    "westeurope",
]


def load_worker_pools(file_path: str) -> list[dict[str, Any]]:
    """Load and parse the worker-pools.yml file."""
    with open(file_path) as f:
        data = yaml.safe_load(f)

    # The worker-pools.yml file has a 'pools' key containing the list of pools
    if isinstance(data, dict) and "pools" in data:
        return data["pools"]

    raise ValueError(
        f"Expected worker pools file to have a 'pools' key, got keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}"
    )


def find_target_pools(pools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find pools with provider_id = azure2."""
    return [pool for pool in pools if "azure" in pool.get("provider_id")]


def extract_vm_sizes_and_locations(pool: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract VM sizes and locations from a pool configuration."""
    vm_info = []

    config = pool.get("config", {})
    launch_configs = config.get("vmSizes", [])

    # Extract locations from config
    # !!! NOTE: We use hiphens in worker-pools.yml, but Azure API uses no hiphens
    locations = [l.replace("-", "") for l in config.get("locations", [])]

    for launch_cfg in launch_configs:
        vm_size = (
            launch_cfg.get("launchConfig", {})
            .get("hardwareProfile", {})
            .get("vmSize", launch_cfg.get("vmSize"))
        )
        vm_info.append(
            {"pool_id": pool["pool_id"], "vm_size": vm_size, "locations": locations}
        )

    return vm_info


def resolve_variants(pools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve pool variants into individual pool configurations."""
    resolved_pools = []

    def _evaluate_keyed_by(p):
        """Evaluate all keyed-by entries in the pool configuration."""
        for key in ("provider_id", "config.locations"):
            resolve_keyed_by(p, key, p["pool_id"], **p.get("attributes", {}))
        for vmSize in p["config"].get("vmSizes", []):
            for key in ("vmSize", "launchConfig.hardwareProfile.vmSize"):
                resolve_keyed_by(vmSize, key, p["pool_id"], **p.get("attributes", {}))

    for pool in pools:
        variants = pool.pop("variants", None)
        if variants:
            for variant in variants:
                # Create a new pool dict combining base and variant
                new_pool = copy.deepcopy(pool)
                new_pool.setdefault("attributes", {}).update(variant)
                _evaluate_keyed_by(new_pool)
                resolved_pools.append(new_pool)
        else:
            _evaluate_keyed_by(pool)
            resolved_pools.append(pool)

    return resolved_pools


@functools.cache
def query_azure_pricing(vm_size: str) -> dict[str, Any]:
    """Query Azure pricing API for a specific VM size."""
    # Default regions commonly used
    pricing_data = {}

    if not vm_size:
        raise Exception("VM size is required to query pricing")

    # Build the API URL with filters
    base_url = "https://prices.azure.com/api/retail/prices"

    # Filter for the specific VM size and region
    filter_params = [
        f"armSkuName eq '{vm_size}'",
        "contains(meterName, 'Spot')",
    ]
    if vm_size == "Standard_D16ps_v5":
        filter_params.insert(0, "priceType eq 'DevTestConsumption'")

    filter_query = " and ".join(filter_params)
    url = f"{base_url}?$filter={quote(filter_query)}"

    try:
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()
        items = data.get("Items", [])
        if not items:
            pricing_data["error"] = {"error": f"No pricing data found for {vm_size}"}
            return pricing_data

        for item in items:
            pricing_data[item.get("armRegionName")] = {
                "currency_code": item.get("currencyCode"),
                "retail_price": item.get("retailPrice"),
                "unit_price": item.get("unitPrice"),
                "unit_of_measure": item.get("unitOfMeasure"),
                "product_name": item.get("productName"),
                "sku_name": item.get("skuName"),
                "service_name": item.get("serviceName"),
            }

    except requests.RequestException as e:
        pricing_data["error"] = {"error": f"API request failed: {str(e)}"}

    return pricing_data


def main():
    """Main function to process worker pools and query pricing."""
    worker_pools_file = Path(__file__).parent.parent / "worker-pools.yml"

    try:
        # Load worker pools
        pools = load_worker_pools(worker_pools_file)
        print(f"Loaded {len(pools)} worker pools")

        # Resolve variants
        pools = resolve_variants(pools)
        print(f"Resolved to {len(pools)} pool configurations after variants")

        # Find target pools (Azure2 provider)
        pools = find_target_pools(pools)
        print(f"Found {len(pools)} Azure2 pools:")

        for pool in pools:
            pool["pool_id"] = pool["pool_id"].format(**pool.get("attributes", {}))
            print(f"  - {pool['pool_id']}")

        # Process each target pool
        for pool in pools:
            print(f"\nProcessing pool: {pool['pool_id']}")

            vm_info = extract_vm_sizes_and_locations(pool)

            for vm in vm_info:
                vm_size = vm["vm_size"]
                pool_locations = vm.get("locations", set())
                missing_locations = set(pool_locations) - set(LOCATIONS)
                print(f"  VM Size: {vm_size}")

                # Query pricing for this VM size
                pricing = query_azure_pricing(vm_size)
                print(f"  Pricing data for {vm_size}:")

                missing_locations = set(pool_locations) - set(pricing.keys())
                if missing_locations:
                    print(
                        f"!!!! Warning: No pricing data found for the following locations: {', '.join(missing_locations)}"
                    )

                # Sort regions by price (ascending)
                sorted_pricing = sorted(
                    pricing.items(),
                    key=lambda x: x[1].get("retail_price", float("inf")),
                )

                for price_location, price_info in sorted_pricing:
                    # Check if this region is in the pool's configured locations
                    if price_location in pool_locations:
                        region_marker = "·"
                    else:
                        region_marker = " "

                    if "error" in price_info:
                        print(
                            f"  {region_marker} {price_location:<18}: {price_info['error']}"
                        )
                    else:
                        retail_price = price_info.get("retail_price", "N/A")
                        currency = price_info.get("currency_code", "N/A")
                        unit = price_info.get("unit_of_measure", "N/A")
                        print(
                            f"  {region_marker} {price_location:<18}: {retail_price:<8} {currency}/{unit}"
                        )

                print()

    except FileNotFoundError:
        print(f"Error: Could not find worker-pools.yml file at {worker_pools_file}")
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
    # except Exception as e:
    # print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
