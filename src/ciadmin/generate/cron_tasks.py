# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import copy
import re
import textwrap

import jsone
from tcadmin.resources import Binding, Hook, Role
from tcadmin.util.root_url import root_url

from .ciconfig.environment import Environment
from .ciconfig.get import get_ciconfig_file
from .ciconfig.projects import Project

GITHUB_TOKEN_SECRET = "project/releng/mobile/github-cron-token"


async def make_hooks(project, environment):
    hookGroupId = "project-releng"
    hookId = "cron-task-{}".format(project.repo_path.replace("/", "-"))

    if project.feature("gecko-cron"):
        cron_config = environment.cron.get("gecko", {})
    elif project.feature("taskgraph-cron"):
        cron_config = environment.cron.get("taskgraph", {})
    else:
        raise Exception("Unknown cron task type.")

    context = {
        "level": project.level,
        "trust_domain": project.trust_domain,
        "hookGroupId": hookGroupId,
        "hookId": hookId,
        "taskcluster_root_url": await root_url(),
        "project_repo": project.repo,
        "alias": project.alias,
        "trim_whitespace": lambda s: re.sub(r"\s+", " ", s).strip(),
        "repo_type": project.repo_type,
        "cron_options": [],
        "allow_input": False,
        "branch": project.default_branch,
        "cron_notify_emails": project.cron.get(
            "notify_emails", cron_config.get("notify_emails", [])
        ),
        "hooks_owner": project.cron.get(
            "hooks_owner", cron_config.get("hooks_owner", "")
        ),
    }
    if "github.com" in project.repo:
        context["cron_options"].extend(["--github-token-secret", GITHUB_TOKEN_SECRET])

    # use the cron-task-template.yml from the ci-configuration repository, rendering it
    # with the context values described there
    task_template = await get_ciconfig_file("cron-task-template.yml")
    task = jsone.render(task_template, context)

    resources = [
        Hook(
            hookGroupId=hookGroupId,
            hookId=hookId,
            name="{}/{}".format(hookGroupId, hookId),
            description=textwrap.dedent(
                """\
        Cron task for repository {}.

        This hook is fired every 15 minutes, creating a task that consults .cron.yml in
        the corresponding repository.
        """
            ).format(project.repo),
            owner=context["hooks_owner"],
            emailOnError=True,
            schedule=["0 0,15,30,45 * * * *"],  # every 15 minutes
            bindings=[],
            task=task,
            # this schema simply requires an empty object (the default)
            triggerSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        Role(
            roleId="hook-id:{}/{}".format(hookGroupId, hookId),
            description="Scopes associated with cron tasks for project `{}`".format(
                project.alias
            ),
            # this task has the scopes of *all* cron tasks in this project;
            # the tasks it creates will have the scopes for a specific cron task
            # (replacing * with the task name)
            scopes=[
                "assume:{}:cron:*".format(project.role_prefix),
                "queue:route:notify.email.*",
                "queue:create-task:highest:infra/build-decision",
            ],
        ),
    ]

    for target_desc in project.cron.get("targets", []):
        cron_target = target_desc["target"]
        pulse_bindings = target_desc.get("bindings", [])
        # Default to allowing input if we are bound to a pulse exchgange.
        allow_input = target_desc.get("allow-input", bool(pulse_bindings))
        branch = target_desc.get("branch", project.default_branch)

        target_context = copy.deepcopy(context)
        target_context["cron_options"] += ["--force-run={}".format(cron_target)]
        target_context["hookId"] = "{}/{}".format(hookId, cron_target)
        target_context["allow_input"] = allow_input
        target_context["branch"] = branch
        task = jsone.render(task_template, target_context)
        scopes = [
            "assume:{}:cron:{}".format(project.role_prefix, cron_target),
            "queue:route:notify.email.*",
            "queue:create-task:highest:infra/build-decision",
        ]
        if "github.com" in project.repo:
            scopes.append("secrets:get:{}".format(GITHUB_TOKEN_SECRET))

        resources.extend(
            [
                Hook(
                    hookGroupId=hookGroupId,
                    hookId="{}/{}".format(hookId, cron_target),
                    name="{}/{}/{}".format(hookGroupId, hookId, cron_target),
                    description="""FIXME""",
                    owner=target_context["hooks_owner"],
                    emailOnError=True,
                    schedule=[],
                    bindings=[
                        Binding(
                            exchange=binding["exchange"],
                            routingKeyPattern=binding["routing_key_pattern"],
                        )
                        for binding in pulse_bindings
                    ],
                    task=task,
                    # this schema simply requires an empty object (the default)
                    triggerSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": allow_input,
                    },
                ),
                Role(
                    roleId="hook-id:{}/{}/{}".format(hookGroupId, hookId, cron_target),
                    description="Scopes associated with cron tasks "
                    "for project `{}`".format(project.alias),
                    scopes=scopes,
                ),
            ]
        )

    return resources


async def update_resources(resources):
    """
    Manage the hooks and roles for cron tasks
    """
    projects = await Project.fetch_all()
    environment = await Environment.current()

    # manage the cron-task-* hooks, and corresponding roles;
    # these are all nested under project-releng
    # but should probably move to project-{gecko,comm} someday..
    resources.manage("Hook=project-releng/cron-task-.*")
    resources.manage("Role=hook-id:project-releng/cron-task-.*")

    for project in projects:
        # if this project does not thave the `gecko-cron` feature, it does not get
        # a hook.
        if not project.feature("gecko-cron") and not project.feature("taskgraph-cron"):
            continue

        resources.update(await make_hooks(project, environment))
