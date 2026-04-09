# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import textwrap

import jsone
from tcadmin.resources import Hook, Role

from .ciconfig.get import get_ciconfig_file
from .ciconfig.projects import Project


async def make_hook(project: Project, branch) -> Hook:
    hookGroupId = "git-push"
    hookId = f"{project.role_prefix.removeprefix('repo:')}:branch:{branch.name}"

    task_template = await get_ciconfig_file("git-push-template.yml")
    task = jsone.render(
        task_template,
        {
            "level": branch.level,
            "trust_domain": project.trust_domain,
            "hookGroupId": hookGroupId,
            "hookId": hookId,
            "project_repo": project.repo,
            "project_role_prefix": project.role_prefix,
            "alias": project.alias,
        },
    )

    return Hook(
        hookGroupId=hookGroupId,
        hookId=hookId,
        name=f"{hookGroupId}/{hookId}",
        description=textwrap.dedent(
            """\
            On-push task for branch `{}` of repository {}.

            This hook is triggered manually by in-repo tooling and creates a decision task.
            """
        ).format(branch.name, project.repo),
        owner="release+tc-hooks@mozilla.com",
        emailOnError=False,
        schedule=[],
        bindings=(),
        task=task,
        triggerSchema={
            "type": "object",
            "required": ["base_sha", "owner", "ref", "sha"],
            "properties": {
                "base_ref": {
                    "type": ["string", "null"],
                    "description": "The base ref for the push, if any.",
                    "default": None,
                },
                "base_sha": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{40}$",
                    "description": "The commit SHA before the push.",
                },
                "owner": {
                    "type": "string",
                    "format": "email",
                    "description": "The email address of the user who pushed.",
                    "default": "nobody@mozilla.com",
                },
                "ref": {
                    "type": "string",
                    "description": "The git ref that was pushed (e.g. refs/heads/main).",
                },
                "sha": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{40}$",
                    "description": "The commit SHA after the push.",
                },
            },
            "additionalProperties": False,
        },
    )


async def update_resources(resources):
    """
    Manage the hooks and roles for git-push resources.
    """
    projects = await Project.fetch_all()
    projects = [p for p in projects if p.feature("git-push")]

    resources.manage("Hook=git-push/.*")
    resources.manage("Role=hook-id:git-push/.*")

    for project in projects:
        for branch in project.branches:
            hook = await make_hook(project, branch)
            resources.add(hook)

            role = Role(
                roleId=f"hook-id:{hook.hookGroupId}/{hook.hookId}",
                description=f"Scopes associated with git pushes to branch `{branch.name}` of project `{project.alias}`",
                scopes=[
                    f"assume:repo:{hook.hookId}",
                    f"queue:route:index.git-push.v1.{project.alias}.*",
                    "queue:create-task:highest:infra/build-decision",
                ],
            )
            resources.add(role)
