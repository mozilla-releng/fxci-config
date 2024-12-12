# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import copy
import json
import os
import re
import shlex
from sys import orig_argv
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


def load_fetches(moz_fetches: dict | str) -> list[dict[str, Any]]:
    if isinstance(moz_fetches, str):
        ret = json.loads(moz_fetches)
        if not isinstance(ret, list):
            raise Exception("non-list fetches are not supported at this time")
        return ret
    else:
        return []


def rewrite_private_fetches(taskdesc: dict[str, Any]) -> None:
    """Re-write fetches that use private artifacts to the equivalent `firefoxci-artifact`
    task.
    """
    payload = taskdesc["task"]["payload"]
    deps = taskdesc.setdefault("dependencies", {})

    if "MOZ_FETCHES" in payload.get("env", {}):
        fetches = load_fetches(payload.get("env", {}).get("MOZ_FETCHES", "[]"))
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


def rewrite_mirrored_dependencies(
    taskdesc: dict[str, Any],
    prefix: str,
    dependencies: dict[str, str],
    mirrored_tasks: dict[str, Any],
    include_deps: list[str],
    artifact_tasks: dict[str, Any],
):
    """Re-write dependencies and fetches of tasks that are being re-run in the
    staging instance. Without this, the downstream tasks will attempt to refer
    to firefoxci task ids that do not exist in the staging cluster, and task
    submission will fail.
    """
    patterns = [re.compile(p) for p in include_deps]
    mirrored_deps = set()
    artifact_deps = set()
    # First, update any dependencies that are also being run as part of this integration test
    for upstream_task_id in dependencies:
        # Some of these may be other tasks that we're mirroring into this cluster...
        if upstream_task_id in mirrored_tasks:
            name = mirrored_tasks[upstream_task_id]["metadata"]["name"]
            if any([pat.match(name) for pat in patterns]):
                mirrored_deps.add(upstream_task_id)
                upstream_task_label = f"{prefix}-{name}"
                taskdesc["dependencies"][upstream_task_label] = upstream_task_label

        # Others may be `firefoxci-artifact` tasks that have mirrored artifacts
        # from firefox ci tasks into this cluster.
        artifact_task_label = f"firefoxci-artifact-{prefix}-{upstream_task_id}"
        if (
            artifact_task_label in artifact_tasks
            and artifact_task_label not in taskdesc["dependencies"].values()
        ):
            artifact_deps.add(upstream_task_id)
            taskdesc["dependencies"][artifact_task_label] = artifact_task_label

    # Second, update any fetches that point to dependencies that are also being run as part
    # of this integration test
    updated_fetches = []
    fetches = load_fetches(
        taskdesc["task"]["payload"].get("env", {}).get("MOZ_FETCHES", "[]")
    )

    if fetches:
        for fetch in fetches:
            fetch_task_id = fetch["task"]
            if fetch_task_id in mirrored_deps:
                fetch_task_label = mirrored_tasks[fetch_task_id]["metadata"]["name"]
                fetch["task"] = f"<{prefix}-{fetch_task_label}>"

            if fetch_task_id in artifact_deps:
                fetch["task"] = f"<firefoxci-artifact-{prefix}-{fetch_task_id}>"

            updated_fetches.append(fetch)

        taskdesc["task"]["payload"]["env"]["MOZ_FETCHES"] = {
            "task-reference": json.dumps(updated_fetches)
        }


def make_integration_test_description(
    task_def: dict[str, Any],
    name_prefix: str,
    mirrored_tasks: dict[str, Any],
    include_deps: list[str],
    artifact_tasks: dict[str, Any],
):
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

    orig_dependencies = task_def["dependencies"]
    del task_def["dependencies"]
    if "treeherder" in task_def["extra"]:
        del task_def["extra"]["treeherder"]

    rewrite_mounts(task_def)
    rewrite_docker_cache(task_def)

    # Drop down to level 1 to match the current context.
    for key in ("taskQueueId", "provisionerId", "worker-type"):
        if key in task_def:
            task_def[key] = task_def[key].replace("3", "1")

    task_def["metadata"]["name"] = f"{name_prefix}-{task_def['metadata']['name']}"
    taskdesc = {
        "label": task_def["metadata"]["name"],
        "description": task_def["metadata"]["description"],
        "task": task_def,
        "dependencies": {
            "apply": "tc-admin-apply-staging",
        },
        "attributes": {"integration": name_prefix},
        "optimization": {
            "integration-test": [
                "taskcluster/fxci_config_taskgraph/**",
                "taskcluster/kinds/firefoxci-artifact/kind.yml",
                "taskcluster/kinds/integration-test/kind.yml",
            ]
        },
    }
    rewrite_docker_image(taskdesc)
    rewrite_private_fetches(taskdesc)
    rewrite_mirrored_dependencies(
        taskdesc,
        name_prefix,
        orig_dependencies,
        mirrored_tasks,
        include_deps,
        artifact_tasks,
    )
    # Tasks may only have 1 root url set, which is primarily used to decide
    # where to find `MOZ_FETCHES`. When all of our fetches are known to be
    # running in the staging cluster, we do not need to patch the root url.
    # If they're all running in production, we must patch it. If we have a mix
    # of both, we cannot proceed, as either the stage or production ones would
    # result in 404s at runtime.
    fetches = json.loads(
        task_def.get("payload", {})
        .get("env", {})
        .get("MOZ_FETCHES", {})
        .get("task-reference", "{}")
    )
    task_locations = set()
    for f in fetches:
        name = f["task"].strip("<>")
        # It would be preferable if we checked for full task labels rather
        # than relying on a prefix, but because tasks created by this transform
        # depend on one another, and we don't try to create them in graph order,
        # there's no guarantee that this check would reliably.
        if name in artifact_tasks or name.startswith(f"{name_prefix}-"):
            task_locations.add("stage")
        else:
            task_locations.add("prod")

    if len(task_locations) == 2:
        raise Exception(
            "Cannot run a task with fetches from stage and production clusters."
        )

    if "prod" in task_locations:
        patch_root_url(task_def)

    return taskdesc


@transforms.add
def schedule_tasks_at_index(config, tasks):
    # Filter out tasks here rather than the target phase because generating
    # their definitions makes a bunch of Taskcluster API calls that aren't
    # necessary in the common case.
    if os.environ["TASKCLUSTER_ROOT_URL"] != STAGING_ROOT_URL:
        return

    artifact_tasks = {
        k: v
        for k, v in config.kind_dependencies_tasks.items()
        if k.startswith("firefoxci-artifact")
    }
    for task in tasks:
        include_attrs = task.pop("include-attrs", {})
        exclude_attrs = task.pop("exclude-attrs", {})
        include_deps = task.pop("include-deps", [])
        for decision_index_path in task.pop("decision-index-paths"):
            # `find_tasks` can return tasks with duplicate labels when
            # `include_deps` is used (eg: graphs with leaf nodes that have
            # different instances of the same ancestor task due to caching).
            # To deal with this, we keep track of task names we create and
            # ensure we only create each once.
            created_tasks = set()

            found_tasks = find_tasks(
                decision_index_path,
                include_attrs,
                exclude_attrs,
                include_deps,
            )

            for task_def in found_tasks.values():
                # `task_def` will be modified by the function called below;
                # we need a copy of the original name to add it to
                # `created_tasks` afterwards
                orig_name = task_def["metadata"]["name"]
                if orig_name not in created_tasks:
                    # task_def is copied to avoid modifying the version in `tasks`, which
                    # may be used to modify parts of the new task description
                    yield make_integration_test_description(
                        copy.deepcopy(task_def),
                        task["name"],
                        found_tasks,
                        include_deps,
                        artifact_tasks,
                    )

                created_tasks.add(orig_name)
