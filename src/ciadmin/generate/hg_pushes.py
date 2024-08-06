# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import textwrap

import jsone
from tcadmin.resources import Binding, Hook, Role

from .ciconfig.get import get_ciconfig_file
from .ciconfig.projects import Project


async def make_hook(project):
    hookGroupId = "hg-push"
    hookId = project.alias

    if project.taskcluster_yml_project:
        taskcluster_yml_project = await Project.get(project.taskcluster_yml_project)
        if project.level > taskcluster_yml_project.level:
            raise ValueError(
                f"Cannot use `.taskcluster.yml` from {project.taskcluster_yml_project} which has level {taskcluster_yml_project.level}, "
                f"for {project.alias} which has level {project.level}."
            )
        taskcluster_yml_repo = taskcluster_yml_project.repo
    else:
        taskcluster_yml_repo = None

    # use the hg-push-template.yml from the ci-configuration repository, rendering it
    # with the context values described there
    task_template = await get_ciconfig_file("hg-push-template.yml")

    task = jsone.render(
        task_template,
        {
            "level": project.default_branch_level,
            "trust_domain": project.trust_domain,
            "hookGroupId": hookGroupId,
            "hookId": hookId,
            "project_repo": project.repo,
            "project_role_prefix": project.role_prefix,
            "alias": project.alias,
            "taskcluster_yml_repo": taskcluster_yml_repo,
        },
    )

    return Hook(
        hookGroupId=hookGroupId,
        hookId=hookId,
        name=f"{hookGroupId}/{hookId}",
        description=textwrap.dedent(
            """\
            On-push task for repository {}.

            This hook listens to pulse messages from `hg.mozilla.org` and creates
            a task which quickly creates a decision task when such a message arrives.
            """
        ).format(project.repo),
        owner="release+tc-hooks@mozilla.com",
        emailOnError=False,
        schedule=[],
        bindings=(
            Binding(
                exchange="exchange/hgpushes/v2", routingKeyPattern=project.repo_path
            ),
        ),
        task=task,
        triggerSchema={
            "type": "object",
            "required": ["payload"],
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "Hg push payload - see "
                    "https://mozilla-version-control-tools.readthedocs.io"
                    "/en/latest/hgmo/notifications.html#pulse-notifications.",
                    "required": ["type", "data"],
                    "properties": {
                        "type": {"enum": ["changegroup.1"], "default": "changegroup.1"},
                        "data": {
                            "type": "object",
                            "required": ["repo_url", "heads", "pushlog_pushes"],
                            "properties": {
                                "repo_url": {
                                    "enum": [project.repo],
                                    "default": project.repo,
                                },
                                "heads": {
                                    "type": "array",
                                    # a tuple pattern, limiting this to an
                                    # array of length exactly 1
                                    "items": [
                                        {"type": "string", "pattern": "^[0-9a-z]{40}$"}
                                    ],
                                },
                                "pushlog_pushes": {
                                    "type": "array",
                                    # a tuple pattern, limiting this to an
                                    # array of length exactly 1
                                    "items": [
                                        {
                                            "type": "object",
                                            "required": ["time", "pushid", "user"],
                                            "properties": {
                                                "time": {
                                                    "type": "integer",
                                                    "default": 0,
                                                },
                                                "pushid": {
                                                    "type": "integer",
                                                    "default": 0,
                                                },
                                                "user": {
                                                    "type": "string",
                                                    "format": "email",
                                                    "default": "nobody@mozilla.com",
                                                },
                                                # not used by the hook
                                                # but allowed here for copy-pasta:
                                                "push_json_url": {"type": "string"},
                                                "push_full_json_url": {
                                                    "type": "string"
                                                },
                                            },
                                            "additionalProperties": False,
                                        }
                                    ],
                                },
                                # not used by this hook,
                                # but allowed here for copy-pasta:
                                "source": {},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                # not used by this hook, but allowed here for copy-pasta:
                "_meta": {},
            },
            "additionalProperties": False,
        },
    )


async def update_resources(resources):
    """
    Manage the hooks and roles for cron tasks
    """
    projects = await Project.fetch_all()
    projects = [p for p in projects if p.feature("hg-push")]
    trust_domains = set(project.trust_domain for project in projects)

    # manage the hg-push/* hooks, and corresponding roles
    for trust_domain in trust_domains:
        resources.manage("Hook=hg-push/.*")
        resources.manage("Role=hook-id:hg-push/.*")

    for project in projects:
        hook = await make_hook(project)
        resources.add(hook)

        role = Role(
            roleId=f"hook-id:{hook.hookGroupId}/{hook.hookId}",
            description=f"Scopes associated with hg pushes for project `{project.alias}`",
            scopes=[
                f"assume:{project.role_prefix}:branch:*",
                f"queue:route:index.hg-push.v1.{project.alias}.*",
                # all hg-push tasks use the same workerType,
                # and branches do not have permission to create tasks on that workerType
                "queue:create-task:highest:infra/build-decision",
            ],
        )
        resources.add(role)
