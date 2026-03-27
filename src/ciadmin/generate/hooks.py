# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


from tcadmin.resources import Binding, Hook, Role

from .ciconfig.externally_managed import (
    get_externally_managed_patterns,
    manage_individual,
    manage_with_exclusions,
)
from .ciconfig.get import get_ciconfig_file
from .ciconfig.hooks import Hook as HookConfig


async def update_resources(resources):
    """
    Manage custom hooks.  This file interprets `hooks.yml` in fxci-config.
    Its behavior is largely documented in the comment in that file.
    """

    hooks = await HookConfig.fetch_all()
    ext_patterns = await get_externally_managed_patterns()

    manage_with_exclusions(resources, "Hook=.*", ext_patterns)
    manage_with_exclusions(resources, "Role=hook-id:.*", ext_patterns)

    for hook in hooks:
        hook_name = f"{hook.hook_group_id}/{hook.hook_id}"

        # For hooks in externally-managed namespaces, explicitly manage
        # the individual resources we generate
        manage_individual(resources, f"Hook={hook_name}")
        manage_individual(resources, f"Role=hook-id:{hook_name}")

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
