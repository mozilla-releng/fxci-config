# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import re
from functools import cache
from typing import Any

import requests
import taskcluster
from taskgraph.util.attributes import attrmatch
from taskgraph.util.taskcluster import get_ancestors as taskgraph_get_ancestors
from taskgraph.util.taskcluster import get_root_url

from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL


def get_ancestors(task_ids: list[str] | str) -> dict[str, str]:
    # This is not ideal, but at the moment we don't have a better way
    # to ensure that the upstream get_ancestors talks to the correct taskcluster
    # instance.
    orig = os.environ["TASKCLUSTER_ROOT_URL"]
    try:
        # Cache needs to be cleared here to allow `get_root_url` to ensure that
        # `get_root_url` is called again after a change.
        get_root_url.cache_clear()
        os.environ["TASKCLUSTER_ROOT_URL"] = FIREFOXCI_ROOT_URL
        ret = taskgraph_get_ancestors(task_ids)
    finally:
        os.environ["TASKCLUSTER_ROOT_URL"] = orig
        get_root_url.cache_clear()

    return ret


@cache
def get_taskcluster_client(service: str):
    options = {"rootUrl": FIREFOXCI_ROOT_URL}
    return getattr(taskcluster, service.capitalize())(options)


@cache
def _fetch_task_graph(decision_index_path: str) -> dict[str, dict[str, Any]]:
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

    return task_graph


@cache
def _queue_task(task_id):
    queue = get_taskcluster_client("queue")
    return queue.task(task_id)


def _rewrite_task_datestamps(task_def):
    """Rewrite absolute datestamps from a concrete task definition into
    relative ones that can then be used to schedule a new task."""
    # Arguably, we should try to figure out what these values should be from
    # the repo that created them originally. In practice it probably doesn't
    # matter.
    task_def["created"] = {"relative-datestamp": "0 seconds"}
    task_def["deadline"] = {"relative-datestamp": "1 day"}
    task_def["expires"] = {"relative-datestamp": "1 month"}

    if "payload" in task_def:
        if "artifacts" in task_def["payload"]:
            if isinstance(task_def["payload"]["artifacts"], dict):
                for key, _ in task_def["payload"]["artifacts"].items():
                    if "expires" in task_def["payload"]["artifacts"][key]:
                        task_def["payload"]["artifacts"][key]["expires"] = {
                            "relative-datestamp": "1 month"
                        }
            elif isinstance(task_def["payload"]["artifacts"], list):
                new_artifacts = []
                for a in task_def["payload"]["artifacts"]:
                    if "expires" in a:
                        a["expires"] = {"relative-datestamp": "1 month"}
                    new_artifacts.append(a)
                task_def["payload"]["artifacts"] = new_artifacts

    return task_def


def find_tasks(
    decision_index_path: str,
    include_attrs: dict[str, list[str]],
    exclude_attrs: dict[str, list[str]],
    include_deps: list[str],
) -> dict[str, dict[str, Any]]:
    """Find and return tasks targeted by the Decision task pointed to by
    `decision_index_path` that match the the included and excluded attributes
    given. Any tasks upstream of a targeted task will also be returned if
    their label matches any pattern given in `include_deps`. (Note that
    attributes _cannot_ be used to filter upstream tasks, as we only have
    access to task definitions for these tasks.)
    """
    tasks = {}

    for task_id, task in _fetch_task_graph(decision_index_path).items():
        assert isinstance(task, dict)
        attributes = task.get("attributes", {})
        if not attrmatch(attributes, **include_attrs):
            continue

        if exclude_attrs:
            excludes = {
                key: lambda attr: any([attr.startswith(v) for v in values])
                for key, values in exclude_attrs.items()
            }
            if attrmatch(attributes, **excludes):
                continue

        tasks[task_id] = task["task"]
        # get_ancestors can be expensive; don't run it unless we might actually
        # use the results.
        if include_deps:
            patterns = [re.compile(p) for p in include_deps]
            for upstream_task_id, label in get_ancestors(task_id).items():
                if any([pat.match(label) for pat in patterns]):
                    task_def = _queue_task(upstream_task_id)
                    # The task definitions from `get_ancestors` are fully
                    # concrete, unlike the ones that `_fetch_task_graph`
                    # returns, which have certain things missing or in a
                    # different form. We need to massage the former to look
                    # like the latter to allow callers to treat them the same.

                    # `taskQueueId` should never be present, because it will
                    # never match what it ought to be when we reschedule tasks
                    # in staging.
                    if "taskQueueId" in task_def:
                        del task_def["taskQueueId"]

                    # All datestamps come in as absolute ones, many of which
                    # will be in the past. We need to rewrite these to relative
                    # ones to make the task reschedulable.
                    tasks[upstream_task_id] = _rewrite_task_datestamps(task_def)

    return tasks
