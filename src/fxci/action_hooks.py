# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
import re
import sys

import yaml
from taskcluster import optionsFromEnvironment
from taskcluster.aio import Hooks, Queue
from taskcluster.exceptions import TaskclusterRestFailure
from tcadmin.util.sessions import aiohttp_session, with_aiohttp_session

from ciadmin.generate import tcyml
from ciadmin.generate.ciconfig.actions import Action
from ciadmin.generate.ciconfig.projects import Project
from ciadmin.generate.in_tree_actions import (
    hashed_tcyml,
    make_hooks,
    parse_and_hash,
    supports_actions,
)


async def _fetch_task(task_id):
    queue = Queue(optionsFromEnvironment(), session=aiohttp_session())
    return await queue.task(task_id)


async def _fetch_artifact(task_id, name):
    queue = Queue(optionsFromEnvironment(), session=aiohttp_session())
    url = queue.buildUrl("getLatestArtifact", task_id, name)
    async with aiohttp_session().get(url) as response:
        response.raise_for_status()
        return await response.read()


def _decision_task_origin(task, projects):
    """
    Find the (project, branch) a decision task was created for.

    Uses the task's `assume:repo:..` scope rather than its parameters.
    Taskcluster only lets a task carry that scope if its creator held it, so a
    lower level push can't fake it.
    """
    origins = set()
    for project in projects:
        prefix = f"assume:{project.role_prefix}:"
        for scope in task["scopes"]:
            if scope.startswith(prefix + "branch:"):
                name = scope[len(prefix + "branch:") :]
                if project.get_branch(name) is not None:
                    origins.add((project.alias, name))
            elif scope.startswith(prefix + "cron:"):
                origins.add((project.alias, project.default_branch.name))

    if len(origins) != 1:
        raise ValueError(
            "could not find the single repository branch or cron job this task "
            f"was created for in its scopes {task['scopes']}; pull requests are "
            "not supported"
        )
    alias, branch = origins.pop()
    return next(p for p in projects if p.alias == alias), branch


async def make_decision_task_hooks(task_id):
    """
    Make the action hooks for the `.taskcluster.yml` that decision task
    `task_id` was created from.

    Use this for pushes that `update_resources` doesn't hash, such as try,
    where any push can change `.taskcluster.yml`. The file is baked into the
    hooks as-is, so review it first.

    The next apply deletes these hooks unless they were fired within
    `HOOK_RETENTION_TIME`, so fire them soon after creating them.
    """
    projects = await Project.fetch_all()
    task = await _fetch_task(task_id)
    project, branch = _decision_task_origin(task, projects)
    if not supports_actions(project):
        raise ValueError(f"{project.alias} does not support in-tree actions")

    parameters = yaml.safe_load(await _fetch_artifact(task_id, "public/parameters.yml"))
    revision = parameters["head_rev"]
    # Fetch from the project's repository rather than `head_repository`, so a
    # fork's `.taskcluster.yml` never gets the project's level.
    tcy = await tcyml.get(project.repo, repo_type=project.repo_type, revision=revision)
    parsed = parse_and_hash(tcy)
    if parsed is None:
        raise ValueError(f"{project.alias} {revision} has no usable `.taskcluster.yml`")
    tcyml_hash = parsed[1]

    # `actions.json` names the hooks the decision task expects. Check we'd
    # create those, not hooks for a different `.taskcluster.yml`.
    actions_json = json.loads(await _fetch_artifact(task_id, "public/actions.json"))
    expected = {
        a["hookId"].rsplit("/", 1)[1]
        for a in actions_json["actions"]
        if a.get("kind") == "hook"
    }
    if expected != {tcyml_hash}:
        raise ValueError(
            f"{project.alias} {revision} `.taskcluster.yml` hashes as "
            f"{tcyml_hash}, but the decision task expects {sorted(expected)}"
        )

    # The same hooks `update_resources` would make if it hashed this branch.
    hashed_tcymls = {project.alias: {branch: hashed_tcyml(project, branch, parsed)}}
    return list(
        make_hooks(
            await Action.fetch_all(),
            [p for p in projects if supports_actions(p)],
            hashed_tcymls,
        )
    )


@with_aiohttp_session
async def create_action_hooks(*, task_id, filter=None, dry_run=False):
    hooks = await make_decision_task_hooks(task_id)
    if filter:
        pattern = re.compile(filter)
        hooks = [h for h in hooks if pattern.search(f"{h.hookGroupId}/{h.hookId}")]
        if not hooks:
            sys.exit(f"no hooks match {filter!r}")

    if dry_run:
        for hook in hooks:
            print(hook)
        return

    client = Hooks(optionsFromEnvironment(), session=aiohttp_session())
    for hook in hooks:
        try:
            await client.hook(hook.hookGroupId, hook.hookId)
            print(f"{hook.id} already exists")
            continue
        except TaskclusterRestFailure as e:
            if e.status_code != 404:
                raise
        await client.createHook(hook.hookGroupId, hook.hookId, hook.to_api())
        print(f"created {hook.id}")
