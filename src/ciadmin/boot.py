# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os

import click
from tcadmin.appconfig import AppConfig
from tcadmin.main import main

from ciadmin import modify
from ciadmin.generate import (
    clients,
    cron_tasks,
    git_pushes,
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
    "git_pushes": git_pushes.update_resources,
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

for name, reso_module in RESOURCES.items():
    appconfig.generators.register(reso_module, name=name)

# Registered first so the client is closed even when `modify_resources`
# rejects the environment.
appconfig.modifiers.register(modify.close_github_client)
appconfig.modifiers.register(modify.modify_resources)

appconfig.description_prefix = (
    "*DO NOT EDIT* - This resource is configured automatically by "
    + "[ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
)


def boot():
    if not os.environ.get("GITHUB_TOKEN") and not (
        os.environ.get("GITHUB_APP_ID") and os.environ.get("GITHUB_APP_PRIVKEY")
    ):
        click.echo(
            "WARNING: GITHUB_TOKEN is not present in the environment; you may run into rate limits querying for GitHub branches",
            err=True,
        )

    main(appconfig)
