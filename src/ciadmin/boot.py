# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys

import click
from tcadmin.appconfig import AppConfig
from tcadmin.main import main

from ciadmin import modify
from ciadmin.generate import (
    clients,
    cron_tasks,
    grants,
    hg_pushes,
    hooks,
    in_tree_actions,
    scm_group_roles,
    worker_pools,
)

RESOURCES = {
    "clients": clients.update_resources,
    "cron_tasks": cron_tasks.update_resources,
    "grants": grants.update_resources,
    "hg_pushes": hg_pushes.update_resources,
    "hooks": hooks.update_resources,
    "in_tree_actions": in_tree_actions.update_resources,
    "scm_group_roles": scm_group_roles.update_resources,
    "worker_pools": worker_pools.update_resources,
}

appconfig = AppConfig()

appconfig.options.add(
    "--environment",
    required=True,
    help="environment for which resources are to be generated",
)

appconfig.check_path = os.path.join(os.path.dirname(__file__), "check")

appconfig.modifiers.register(modify.modify_resources)

appconfig.description_prefix = (
    "*DO NOT EDIT* - This resource is configured automatically by "
    + "[ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
)


def boot():
    if not os.environ.get("GITHUB_TOKEN") and not (
        os.environ.get("GITHUB_APP_ID") and os.environ.get("GITHUB_APP_PRIVKEY")
    ):
        print(
            "WARNING: GITHUB_TOKEN is not present in the environment; you may run into rate limits querying for GitHub branches"
        )

    @click.command(
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
    )
    @click.option(
        "--resources",
        required=False,
        default="all",
        help=f"Comma-separated list of resources to generate. Allowed values are: all,{','.join(RESOURCES.keys())}",
    )
    def register_resources_and_run(resources: str):
        resources_list = resources.split(",")
        if "all" in resources_list:
            for reso_module in RESOURCES.values():
                appconfig.generators.register(reso_module)
        else:
            for reso in resources_list:
                if resource_module := RESOURCES.get(reso, None):
                    click.echo(f"Registering resource: {reso}")
                    appconfig.generators.register(resource_module)
                else:
                    click.echo(f"Ignoring invalid resource: {reso}.")
            if "clients" not in resources_list:
                from tcadmin.current import clients
                async def fetch_clients(resources):
                    return
                clients.fetch_clients = fetch_clients

        # Remove the --resources arguments from sys.argv so inner "click.command"s don't complain
        if "--resources" in sys.argv:
            reso_arg_index = sys.argv.index("--resources")
            sys.argv = sys.argv[:reso_arg_index] + sys.argv[reso_arg_index + 2 :]

        main(appconfig)

    # if --help, then add the option to global and let main() handle it
    if "--help" in sys.argv:
        appconfig.options.add(
            "--resources",
            required=False,
            default="all",
            help=f"Comma-separated list of resources to generate. Allowed values are: all,{','.join(RESOURCES.keys())}",
        )
        main(appconfig)
    else:
        register_resources_and_run()
