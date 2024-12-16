# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import shlex
from typing import Any

from taskgraph.transforms.base import TransformSequence

from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL, STAGING_ROOT_URL
from fxci_config_taskgraph.util.integration import find_tasks, get_taskcluster_client

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
        if "content" not in mount:
            continue

        content = mount["content"]
        if "artifact" not in content:
            continue

        if "namespace" in content:
            task_id = index.findTask(content["namespace"])["taskId"]
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
    deps["docker-image"] = (
        f"firefoxci-artifact-{taskdesc['attributes']['integration']}-{task_id}"
    )

    payload["image"] = {
        "path": "public/image.tar.zst",
        "taskId": {"task-reference": "<docker-image>"},
        "type": "task-image",
    }


def rewrite_private_fetches(taskdesc: dict[str, Any]) -> None:
    """Re-write fetches that use private artifacts to the equivalent `firefoxci-artifact`
    task.
    """
    payload = taskdesc["task"]["payload"]
    deps = taskdesc.setdefault("dependencies", {})

    if "MOZ_FETCHES" in payload.get("env", {}):
        fetches = json.loads(payload.get("env", {}).get("MOZ_FETCHES", "{}"))
        modified = False
        for fetch in fetches:
            if fetch["artifact"].startswith("public"):
                continue

            modified = True
            task_id = fetch["task"]
            deps[f"fetch-{task_id}"] = (
                f"firefoxci-artifact-{taskdesc['attributes']['integration']}-{task_id}"
            )
            fetch["task"] = f"<fetch-{task_id}>"

        if modified:
            payload["env"]["MOZ_FETCHES"] = {"task-reference": json.dumps(fetches)}


def make_integration_test_description(task_def: dict[str, Any]):
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

    del task_def["dependencies"]
    if "treeherder" in task_def["extra"]:
        del task_def["extra"]["treeherder"]

    patch_root_url(task_def)
    rewrite_mounts(task_def)
    rewrite_docker_cache(task_def)

    # Drop down to level 1 to match the current context.
    for key in ("taskQueueId", "provisionerId", "worker-type"):
        if key in task_def:
            task_def[key] = task_def[key].replace("3", "1")

    task_def["metadata"]["name"] = f"gecko-{task_def['metadata']['name']}"
    taskdesc = {
        "label": task_def["metadata"]["name"],
        "description": task_def["metadata"]["description"],
        "task": task_def,
        "dependencies": {
            "apply": "tc-admin-apply-staging",
        },
        "attributes": {"integration": "gecko"},
    }
    rewrite_docker_image(taskdesc)
    rewrite_private_fetches(taskdesc)
    return taskdesc


@transforms.add
def schedule_tasks_at_index(config, tasks):
    # Filter out tasks here rather than the target phase because generating
    # their definitions makes a bunch of Taskcluster API calls that aren't
    # necessary in the common case.
    if os.environ["TASKCLUSTER_ROOT_URL"] != STAGING_ROOT_URL:
        return

    for task in tasks:
        for decision_index_path in task.pop("decision-index-paths"):
            for task_def in find_tasks(decision_index_path):
                yield make_integration_test_description(task_def)
