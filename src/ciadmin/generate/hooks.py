# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


from tcadmin.resources import Binding, Hook, Role

from .ciconfig.get import get_ciconfig_file
from .ciconfig.hooks import Hook as HookConfig


async def update_resources(resources):
    """
    Manage custom hooks.  This file interprets `hooks.yml` in ci-configuration.
    Its behavior is largely documented in the comment in that file.
    """

    hooks = await HookConfig.fetch_all()

    resources.manage("Hook=.*")
    resources.manage("Role=hook-id:.*")

    for hook in hooks:
        hook_name = "{}/{}".format(hook.hook_group_id, hook.hook_id)

        task = await get_ciconfig_file(hook.template_file)

        resources.add(
            Role(roleId="hook-id:" + hook_name, description="", scopes=hook.scopes)
        )

        resources.add(
            Hook(
                hookGroupId=hook.hook_group_id,
                hookId=hook.hook_id,
                name=hook.name,
                description=hook.description,
                owner=hook.owner,
                emailOnError=hook.email_on_error,
                schedule=tuple(hook.schedule),
                bindings=[
                    Binding(
                        exchange=binding["exchange"],
                        routingKeyPattern=binding["routing_key_pattern"],
                    )
                    for binding in hook.bindings
                ],
                task=task,
                triggerSchema=hook.trigger_schema,
            )
        )
