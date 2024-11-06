# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
from copy import deepcopy

from taskgraph.transforms.base import TransformSequence

from fxci_config_taskgraph.util.integration import (
    STAGING_ROOT_URL,
    find_tasks,
    get_taskcluster_client,
)

transforms = TransformSequence()


def get_artifact_urls(task_id: str, fetch_artifacts: list[str]) -> str:
    queue = get_taskcluster_client("queue")
    artifacts = queue.listLatestArtifacts(task_id)["artifacts"]

    urls = [
        queue.buildUrl("getLatestArtifact", task_id, artifact["name"]).replace(
            "%2F", "/"
        )
        for artifact in artifacts
        if artifact["name"] in fetch_artifacts
    ]
    return " ".join(urls)


@transforms.add
def make_firefoxci_artifact_tasks(config, tasks):
    if os.environ["TASKCLUSTER_ROOT_URL"] != STAGING_ROOT_URL:
        return

    found_task_ids = set()
    for task in tasks:
        fetch_artifacts = task.pop("fetch-artifacts")

        for decision_index_path in task.pop("decision-index-paths"):
            for task_def in find_tasks(decision_index_path):
                if "image" not in task_def["payload"]:
                    continue

                image = task_def["payload"]["image"]
                if not isinstance(image, dict) or "taskId" not in image:
                    continue

                task_id = image["taskId"]
                if task_id in found_task_ids:
                    continue

                found_task_ids.add(task_id)

                new_task = deepcopy(task)
                new_task["label"] = f"firefoxci-artifact-{task_id}"
                new_task["worker"]["env"]["FETCH_URLS"] = get_artifact_urls(
                    task_id, fetch_artifacts
                )

                yield new_task
