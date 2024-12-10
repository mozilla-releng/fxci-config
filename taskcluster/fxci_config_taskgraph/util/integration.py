# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from functools import cache
from typing import Any

import requests
import taskcluster
from taskgraph.util.taskcluster import get_ancestors

FIREFOXCI_ROOT_URL = "https://firefox-ci-tc.services.mozilla.com"
STAGING_ROOT_URL = "https://stage.taskcluster.nonprod.cloudops.mozgcp.net"


@cache
def get_taskcluster_client(service: str):
    options = {"rootUrl": FIREFOXCI_ROOT_URL}
    return getattr(taskcluster, service.capitalize())(options)


@cache
def find_tasks(decision_index_path: str, include_deps: bool = False) -> list[dict[str, Any]]:
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
        # TODO: move these to kinds and pass them through
        # if attributes.get("unittest_variant") != "os-integration":
        #     continue
        #
        # if attributes.get("test_platform", "").startswith(("android-hw", "macosx")):
        #     continue

        tasks.append(task["task"])
        if include_deps:
            # TODO: remove hack
            import os
            orig = os.environ["TASKCLUSTER_ROOT_URL"]
            os.environ["TASKCLUSTER_ROOT_URL"] = FIREFOXCI_ROOT_URL
            for label, task_id in get_ancestors(task["task_id"]).items():
                # don't want to rerun decision tasks...
                if "Decision" in label:
                    continue
                tasks.append(queue.task(task_id))
            os.environ["TASKCLUSTER_ROOT_URL"] = orig

    return tasks
