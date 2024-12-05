# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import shlex
from typing import Any
import yaml

import jsone
import requests
import slugid
from taskgraph.transforms.base import TransformSequence

from fxci_config_taskgraph.util.integration import (
    FIREFOXCI_ROOT_URL,
    STAGING_ROOT_URL,
    find_tasks,
    get_taskcluster_client,
)

transforms = TransformSequence()


def patch_root_url(task_def):
    """Patch the task's command to trick the task into thinking it is
    running on the firefox-ci instance.

    This is used to make the `fetch-content` script download artifacts from the
    firefoxci instance. This hack only works for public artifacts, as private
    artifacts would need authentication.

    We need to patch the command rather than simply setting
    TASKCLUSTER_ROOT_URL in the task's env, because generic-worker overwrites
    this particular variable.
    """
    if "MOZ_FETCHES" in task_def["payload"].get("env", {}):
        tags = task_def["tags"]
        command = task_def["payload"]["command"]
        if tags.get("os") == "windows":
            command[0] = (
                f'set "TASKCLUSTER_ROOT_URL={FIREFOXCI_ROOT_URL}" & {command[0]}'
            )
        elif tags.get("worker-implementation") == "generic-worker":
            command[1] = [
                "bash",
                "-c",
                f"TASKCLUSTER_ROOT_URL={FIREFOXCI_ROOT_URL} {shlex.join(command[1])}",
            ]
        else:
            command[:] = [
                "bash",
                "-c",
                f"TASKCLUSTER_ROOT_URL={FIREFOXCI_ROOT_URL} {shlex.join(command)}",
            ]


def rewrite_mounts(task_def: dict[str, Any]) -> None:
    """Re-write any mounts that specify a task artifact via index or id to
    instead use the url format.

    This is needed because the task referenced by the mount exists in the
    firefox-ci instance, but won't exist in the staging instance. Using a
    direct url allows us to mount the artifact without depending on the task.
    """
    index = get_taskcluster_client("index")

    for mount in task_def["payload"].get("mounts", []):
        content = mount["content"]
        if "artifact" not in content:
            continue

        if "namespace" in content:
            task_id = index.findTask(content["namespace"])
        else:
            assert "taskId" in content
            task_id = content["taskId"]

        content["url"] = (
            f"{FIREFOXCI_ROOT_URL}/api/queue/v1/task/{task_id}/artifacts/{content['artifact']}"
        )

        del content["artifact"]
        if "namespace" in content:
            del content["namespace"]
        if "taskId" in content:
            del content["taskId"]


def rewrite_docker_cache(task_def: dict[str, Any]) -> None:
    """Adjust docker caches to ci-level-1."""
    cache = task_def["payload"].get("cache")
    if not cache:
        return

    for name, value in cache.copy().items():
        del cache[name]
        name = name.replace("gecko-level-3", "ci-level-1")
        cache[name] = value

    for i, scope in enumerate(task_def.get("scopes", [])):
        task_def["scopes"][i] = scope.replace("gecko-level-3", "ci-level-1")


def rewrite_docker_image(taskdesc: dict[str, Any]) -> None:
    """Re-write the docker-image task id to the equivalent `firefoxci-artifact`
    task.
    """
    payload = taskdesc["task"]["payload"]
    if "image" not in payload or "taskId" not in payload["image"]:
        return

    task_id = payload["image"]["taskId"]
    deps = taskdesc.setdefault("dependencies", {})
    deps["docker-image"] = f"firefoxci-artifact-{task_id}"

    payload["image"] = {
        "path": "public/image.tar.zst",
        "taskId": {"task-reference": "<docker-image>"},
        "type": "task-image",
    }


def make_integration_test_description(task_def: dict[str, Any], additional_dependencies={}):
    """Schedule a task on the staging Taskcluster instance.

    Typically task_def will come from the firefox-ci instance and will be
    modified to work with staging.
    """
    assert "TASK_ID" in os.environ
    task_def.update(
        {
            "schedulerId": "ci-level-1",
            "taskGroupId": os.environ["TASK_ID"],
            "priority": "low",
            "routes": ["checks"],
        }
    )

    if "dependencies" in task_def:
        del task_def["dependencies"]
    if "treeherder" in task_def.get("extra", {}):
        del task_def["extra"]["treeherder"]

    patch_root_url(task_def)
    rewrite_mounts(task_def)
    rewrite_docker_cache(task_def)

    # Drop down to level 1 to match the current context.
    for key in ("taskQueueId", "provisionerId", "worker-type"):
        if key in task_def:
            task_def[key] = task_def[key].replace("3", "1")

    # TODO: remove gecko hardcode here
    task_def["metadata"]["name"] = f"gecko-{task_def['metadata']['name']}"
    dependencies = additional_dependencies.copy()
    dependencies["apply"] = "tc-admin-apply-staging"
    taskdesc = {
        "label": task_def["metadata"]["name"],
        "description": task_def["metadata"]["description"],
        "task": task_def,
        "dependencies": dependencies,
        # TODO: remove gecko hardcodes here
        "attributes": {"integration": "gecko"},
    }
    rewrite_docker_image(taskdesc)
    return taskdesc


def create_decision_task(repo_url: str, repo_name: str, branch: str) -> dict[str, Any]:
    context = {
        "event": {
            # branch isn't technically accurate here...but it's good enough
            "after": branch,
            "before": branch,
            "ref": branch,
            "repository": {
                "html_url": repo_url,
                "name": repo_name,
            },
            "pusher": {
                # TODO: should be inherited from parameters
                "email": "no one",
            },
        },
    }
    return {}


def create_action_task(action: dict):
    """Creates an action task specified by the inputs given. This necessarily
    creates a decision task as well, because action tasks depend on them at
    runtime."""

    repo = action.pop("repo")
    branch = action.pop("branch")
    project = action.pop("project")
    name = action.pop("name")
    perm = action.pop("perm")
    action_input = action.pop("input")
    # TODO: we need a fake decision task, and for this to point at that
    # because we need to pull parameters.yml and probably other things

    decision_taskdef = create_decision_task(repo, project, branch)
    yield decision_taskdef

    taskid = decision_taskdef["taskId"]

    r = requests.get(f"{repo}/raw/{branch}/.taskcluster.yml")
    r.raise_for_status()
    tcyml = yaml.safe_load(r.text)

    context = {
        "tasks_for": "action",
        "repository": {
            "url": repo,
            "project": project,
        },
        "push": {
            "branch": branch,
            "revision": branch,
        },
        "ownTaskId": taskid,
        "taskId": taskid,
        "action": {
            "taskGroupId": taskid,
            "title": name,
            "cb_name": name,
            "name": name,
            "symbol": name,
            "description": f"test of {name} action",
            "action_perm": perm,
        },
        "clientId": "fxci-config",
        "input": action_input,
    }

    yield jsone.render(tcyml, context)["tasks"]


@transforms.add
def schedule_tasks_at_index(config, tasks):
    # Filter out tasks here rather than the target phase because generating
    # their definitions makes a bunch of Taskcluster API calls that aren't
    # necessary in the common case.
    if os.environ["TASKCLUSTER_ROOT_URL"] != STAGING_ROOT_URL:
        return

    for task in tasks:
        if "decision-index-paths" in task:
            for decision_index_path in task.pop("decision-index-paths"):
                for task_def in find_tasks(decision_index_path):
                    # Tasks that depend on private artifacts are not yet supported.
                    fetches = json.loads(
                        task_def["payload"].get("env", {}).get("MOZ_FETCHES", {})
                    )
                    if any(not fetch["artifact"].startswith("public") for fetch in fetches):
                        continue

                    yield make_integration_test_description(task_def)
        if "action" in task:
            for task_def in create_action_task(task.pop("action")):
                from pprint import pprint
                pprint(task_def)
                yield make_integration_test_description(task_def)
