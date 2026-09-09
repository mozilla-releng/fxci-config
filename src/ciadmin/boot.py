# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os

import click
from tcadmin.appconfig import AppConfig
from tcadmin.main import main
from tcadmin.resources import Resources
from tcadmin.util.matchlist import MatchList

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

RESOURCE_MODULES = {
    "clients": clients,
    "cron_tasks": cron_tasks,
    "git_pushes": git_pushes,
    "grants": grants,
    "hg_pushes": hg_pushes,
    "hooks": hooks,
    "in_tree_actions": in_tree_actions,
    "scm_group_roles": scm_group_roles,
    "worker_pools": worker_pools,
}


def _managed_resources(module):
    """Wrap a generator module's `update_resources` so it implicitly claims
    the module's `managed` MatchList before running, instead of requiring
    every module to call `resources.managed.extend(managed)` itself.

    The module only ever sees a `Resources` object scoped to its own
    `managed` list, so `resources.add()` enforces that everything it
    generates is actually covered by its own declaration.
    """

    async def update_resources(resources):
        resources.managed.extend(module.managed)
        scoped = Resources(managed=MatchList(list(module.managed)))
        await module.update_resources(scoped)
        resources.update(scoped)

    return update_resources


appconfig = AppConfig()

appconfig.options.add(
    "--environment",
    required=True,
    help="environment for which resources are to be generated",
)

appconfig.check_path = os.path.join(os.path.dirname(__file__), "check")

for name, reso_module in RESOURCE_MODULES.items():
    appconfig.generators.register(_managed_resources(reso_module), name=name)

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
