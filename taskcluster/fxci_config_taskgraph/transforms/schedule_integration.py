#!/usr/bin/env python3

import os
from functools import cache
from typing import Any

import requests
import taskcluster
from taskgraph.transforms.base import TransformSequence

FIREFOXCI_ROOT_URL = "https://firefox-ci-tc.services.mozilla.com"
STAGING_ROOT_URL = "https://stage.taskcluster.nonprod.cloudops.mozgcp.net"


transforms = TransformSequence()


@cache
def get_taskcluster_client(service: str):
    options = {"rootUrl": FIREFOXCI_ROOT_URL}
    return getattr(taskcluster, service.capitalize())(options)


def find_tasks(decision_index_paths: list[str]) -> list[dict[str, Any]]:
    """Find tasks targetted by the Decision task(s) pointed to by index_paths.

    Defaults to the os-integration cron Decision task in Gecko.
    """
    queue = get_taskcluster_client("queue")
    index = get_taskcluster_client("index")

    tasks = []
    for path in decision_index_paths:
        data = index.findTask(path)
        assert data
        task_id = data["taskId"]

        response = queue.getLatestArtifact(task_id, "public/task-graph.json")
        assert response

        if "url" in response:
            r = requests.get(response["url"])
            r.raise_for_status()
            task_graph = r.json()
        else:
            task_graph = response

        for task in task_graph.values():
            assert isinstance(task, dict)
            if task.get("attributes", {}).get("unittest_variant") != "os-integration":
                continue

            if (
                task["task"].get("tags", {}).get("worker-implementation")
                != "generic-worker"
            ):
                continue

            tasks.append(task["task"])

    return tasks


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
        if tags.get("os") == "windows":
            command = task_def["payload"]["command"]
            command[0] = (
                f'set "TASKCLUSTER_ROOT_URL={FIREFOXCI_ROOT_URL}" & {command[0]}'
            )
        else:
            command = task_def["payload"]["command"]
            command[1] = [
                "bash",
                "-c",
                f"TASKCLUSTER_ROOT_URL={FIREFOXCI_ROOT_URL} {' '.join(command[1])}",
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


def make_task_description(task_def: dict[str, Any]):
    """Schedule a task on the staging Taskcluster instance.

    Typically task_def will come from the firefox-ci instance and will be
    modified to work with staging.
    """
    assert "TASK_ID" in os.environ
    task_def["schedulerId"] = "ci-level-1"
    task_def["taskGroupId"] = os.environ["TASK_ID"]
    task_def["priority"] = "low"
    task_def["routes"] = ["checks"]

    del task_def["dependencies"]
    if "treeherder" in task_def["extra"]:
        del task_def["extra"]["treeherder"]

    patch_root_url(task_def)
    rewrite_mounts(task_def)

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
    return taskdesc


@transforms.add
def schedule_tasks_at_index(config, tasks):
    if (
        os.environ["TASKCLUSTER_ROOT_URL"]
        != "https://stage.taskcluster.nonprod.cloudops.mozgcp.net"
    ):
        return

    for task in tasks:
        for task_def in find_tasks(task.pop("decision-index-paths")):
            yield make_task_description(task_def)
