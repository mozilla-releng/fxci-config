# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


import re
import string

import attr
import yaml
from tcadmin.resources import Binding, Hook, Role

from ..util.keyed_by import resolve_keyed_by
from .ciconfig.hooks import Hook as HookConfig


class HookInterpolator(string.Template):
    """
    A string.Template subclass that uses {var} syntax instead of $var.

    Rules:
      {{           → literal {
      {var}        → replaced with the matching attribute; KeyError if unknown
      ${...}       → left unchanged (JSON-e string interpolation)
      {$eval: ...} → left unchanged (JSON-e operators)
    """

    delimiter = "{"
    flags = re.ASCII
    # Only match {{ (escape) or {word} (simple identifier).
    # Everything else — ${...}, {$eval:...}, etc. — is not matched and passes through.
    # (braced/invalid groups are required by string.Template but never match here)
    pattern = (
        r"\{(?P<escaped>\{)"
        r"|(?<!\$)\{(?P<named>\w+)\}"
        r"|(?P<braced>(?!))"
        r"|(?P<invalid>(?!))"
    )


def generate_hook_variants(hooks):
    """
    Generate the list of hooks by evaluating them at all the specified variants.
    """
    for hook in hooks:
        for variant in hook.variants:
            attributes = hook.attributes.copy()
            attributes.update(variant)

            hook_name = f"{hook.hook_group_id}/{hook.hook_id}"

            fields = {
                "template_file": hook.template_file,
            }
            for field in fields:
                resolve_keyed_by(fields, field, hook_name, **attributes)

            yield attr.evolve(
                hook,
                hook_group_id=hook.hook_group_id.format(**attributes),
                hook_id=hook.hook_id.format(**attributes),
                name=hook.name.format(**attributes),
                description=hook.description.format(**attributes),
                template_file=fields["template_file"].format(**attributes),
                scopes=[s.format(**attributes) for s in hook.scopes],
                attributes=attributes,
                variants=[{}],
            )


async def update_resources(resources):
    """
    Manage custom hooks.  This file interprets `hooks.yml` in fxci-config.
    Its behavior is largely documented in the comment in that file.
    """

    hooks = generate_hook_variants(await HookConfig.fetch_all())

    resources.manage("Hook=.*")
    resources.manage("Role=hook-id:.*")

    for hook in hooks:
        hook_name = f"{hook.hook_group_id}/{hook.hook_id}"

        with open(hook.template_file) as f:
            task = yaml.safe_load(
                HookInterpolator(f.read()).substitute(hook.attributes)
            )

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
