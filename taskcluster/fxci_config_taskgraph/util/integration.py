# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from functools import cache
from typing import Any

import requests
import taskcluster
from taskgraph.util.attributes import attrmatch

from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL


@cache
def get_taskcluster_client(service: str):
    options = {"rootUrl": FIREFOXCI_ROOT_URL}
    return getattr(taskcluster, service.capitalize())(options)


@cache
def _fetch_task_graph(decision_index_path: str) -> list[dict[str, Any]]:
    """Fetch a decision task's `task-graph.json` given by the
    `decision-index-path`. This is done separately from `find_tasks`
    because the @cache decorator does not work with the `dict` parameters
    in `find_tasks`."""
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

    return task_graph.values()


def find_tasks(
    decision_index_path: str,
    include_attrs: dict[str, list[str]],
    exclude_attrs: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Find tasks targeted by the Decision task pointed to by `decision_index_path`
    that match the the included and excluded attributes given.
    """
    tasks = []

    for task in _fetch_task_graph(decision_index_path):
        assert isinstance(task, dict)
        attributes = task.get("attributes", {})
        excludes = {
            key: lambda attr: any([attr.startswith(v) for v in values])
            for key, values in exclude_attrs.items()
        }
        if not attrmatch(attributes, **include_attrs) or attrmatch(
            attributes, **excludes
        ):
            continue

        tasks.append(task["task"])

    return tasks
