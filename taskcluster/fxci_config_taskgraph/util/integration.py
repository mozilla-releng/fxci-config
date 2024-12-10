# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import re
from functools import cache
from typing import Any

import requests
import taskcluster
from taskgraph.util.taskcluster import get_ancestors as taskgraph_get_ancestors

from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL


def get_ancestors(task_ids: list[str] | str) -> dict[str, str]:
    # TODO: this is not ideal, but at the moment we don't have a better way
    # to ensure that the upstream get_ancestors talks to the correct taskcluster
    # instance.
    orig = os.environ["TASKCLUSTER_ROOT_URL"]
    try:
        os.environ["TASKCLUSTER_ROOT_URL"] = FIREFOXCI_ROOT_URL
        ret = taskgraph_get_ancestors(task_ids)
    finally:
        os.environ["TASKCLUSTER_ROOT_URL"] = orig

    return ret


@cache
def get_taskcluster_client(service: str):
    options = {"rootUrl": FIREFOXCI_ROOT_URL}
    return getattr(taskcluster, service.capitalize())(options)


@cache
def find_tasks(
    decision_index_path: str, include_deps: list[re.Pattern] = []
) -> list[dict[str, Any]]:
    """Find tasks targeted by the Decision task pointed to by `decision_index_path`."""
    queue = get_taskcluster_client("queue")
    index = get_taskcluster_client("index")

    data = index.findTask(decision_index_path)
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

    tasks = []
    for task in task_graph.values():
        assert isinstance(task, dict)
        attributes = task.get("attributes", {})
        if attributes.get("unittest_variant") != "os-integration":
            continue

        if attributes.get("test_platform", "").startswith(("android-hw", "macosx")):
            continue

        tasks.append(task["task"])
        # get_ancestors can be expensive; don't run it unless we might actually
        # use the results.
        if include_deps:
            for label, task_id in get_ancestors(task["task_id"]).items():
                if any([pat.match(label) for pat in include_deps]):
                    tasks.append(queue.task(task_id))

    return tasks
