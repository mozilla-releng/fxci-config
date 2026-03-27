#!/usr/bin/env python3
"""
Generate a subset of fxci-config resources without needing GITHUB_TOKEN.
Skips in_tree_actions, cron_tasks, hg_pushes, and scm_group_roles which
need network access or are not relevant to the fuzzing migration.

Usage:
    python generate_subset.py --environment=firefoxci --json > output.json
    python generate_subset.py --environment=firefoxci --text
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from tcadmin.appconfig import AppConfig
from tcadmin.resources import Resources

from ciadmin.generate import (
    clients,
    grants,
    hooks,
    worker_pools,
)

GENERATORS = {
    "clients": clients.update_resources,
    "grants": grants.update_resources,
    "hooks": hooks.update_resources,
    "worker_pools": worker_pools.update_resources,
}


async def generate(environment, resource_types):
    appconfig = AppConfig()
    appconfig.options.add(
        "--environment",
        required=True,
        help="environment",
    )
    appconfig.options = {"--environment": environment, "with_secrets": False}

    with AppConfig._as_current(appconfig):
        resources = Resources()
        for name in resource_types:
            if name in GENERATORS:
                await GENERATORS[name](resources)
        return resources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True)
    parser.add_argument("--json", action="store_true", default=False)
    parser.add_argument(
        "--resources",
        default="all",
        help="Comma-separated list: " + ",".join(GENERATORS.keys()),
    )
    args, _ = parser.parse_known_args()

    if args.resources == "all":
        resource_types = list(GENERATORS.keys())
    else:
        resource_types = args.resources.split(",")

    resources = asyncio.run(generate(args.environment, resource_types))

    if args.json:
        print(json.dumps(resources.to_json(), indent=4, sort_keys=True))
    else:
        print(resources)


if __name__ == "__main__":
    main()
