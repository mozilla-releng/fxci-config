# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


import re
import string

import attr
import yaml
from tcadmin.resources import Binding, Hook, Role
from tcadmin.util.matchlist import Match, MatchList

from ..util.keyed_by import resolve_keyed_by
from .ciconfig.hooks import Hook as HookConfig

# Namespaces managed by other generators, carved out here so we still clean up
# stale hooks without treating theirs as deletions under `--resources hooks`.
_SIBLING_HOOKS = [
    "project-.*/in-tree-action-.*",  # sibling:in_tree_actions
    "project-.*/in-tree-pr-action-.*",  # sibling:in_tree_actions
    "project-releng/cron-task-.*",  # sibling:cron_tasks
    "git-push/.*",  # sibling:git_pushes
    "hg-push/.*",  # sibling:hg_pushes
]

# While fuzzing can mange its own namespaces and are excluded from the blanket
# matches, there are several fuzzing hooks that *do* get managed here.
_FUZZING_HOOKS = [
    "bugmon",
    "coverage-revision",
    "js-tests-distiller",
    "fuzzing-tc-config-community-update",
    "gr-css",
    "gr-idl-update",
    "grizzly-reduce-monitor",
    "grizzly-reduce-reset-error",
    "nss-corpus-update",
    "orion-cron",
]

managed = MatchList(
    [
        Match(
            "Hook=.*",
            excludes=[f"Hook={p}" for p in _SIBLING_HOOKS]
            + ["Hook=project-fuzzing/.*"],  # fuzzing-tc-config
        ),
        Match(
            "Role=hook-id:.*",
            excludes=[f"Role=hook-id:{p}" for p in _SIBLING_HOOKS]
            + ["Role=hook-id:project-fuzzing/.*"],  # fuzzing-tc-config
        ),
    ]
    + [f"Hook=project-fuzzing/{name}" for name in _FUZZING_HOOKS]
    + [f"Role=hook-id:project-fuzzing/{name}" for name in _FUZZING_HOOKS]
)


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

            scopes = [
                s.format(**attributes)
                for s in hook.scopes + variant.get("extra_scopes", [])
            ]

            # Explicitly add the anonymous role to avoid scope errors fetching
            # public/github/customCheckRunText.md (which TC Github looks for).
            scopes.append("assume:anonymous")

            bindings = [
                {f: b[f].format(**attributes) for f in b} for b in hook.bindings
            ]

            yield attr.evolve(
                hook,
                hook_group_id=hook.hook_group_id.format(**attributes),
                hook_id=hook.hook_id.format(**attributes),
                name=hook.name.format(**attributes),
                description=hook.description.format(**attributes),
                template_file=fields["template_file"].format(**attributes),
                schedule=[s.format(**attributes) for s in hook.schedule],
                scopes=scopes,
                attributes=attributes,
                bindings=bindings,
                variants=[{}],
            )


async def update_resources(resources):
    """
    Manage custom hooks.  This file interprets `hooks.yml` in fxci-config.
    Its behavior is largely documented in the comment in that file.
    """

    hooks = generate_hook_variants(await HookConfig.fetch_all())

    for hook in hooks:
        hook_name = f"{hook.hook_group_id}/{hook.hook_id}"

        with open(hook.template_file) as f:
            task = yaml.safe_load(
                HookInterpolator(f.read()).substitute(hook.attributes)
            )

        role = Role(roleId="hook-id:" + hook_name, description="", scopes=hook.scopes)
        resources.add(role)

        hook_resource = Hook(
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
        resources.add(hook_resource)
