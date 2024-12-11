# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
from collections import defaultdict
from copy import deepcopy

from taskgraph.transforms.base import TransformSequence

from fxci_config_taskgraph.util.integration import (
    STAGING_ROOT_URL,
    find_tasks,
)

transforms = TransformSequence()


@transforms.add
def make_firefoxci_artifact_tasks(config, tasks):
    if os.environ["TASKCLUSTER_ROOT_URL"] != STAGING_ROOT_URL:
        return

    for task in tasks:
        # Format: { <task id>: [<artifact name>]}
        tasks_to_create = defaultdict(list)
        for decision_index_path in task.pop("decision-index-paths"):
            for task_def in find_tasks(decision_index_path):
                # Add docker images
                if "image" in task_def["payload"]:
                    image = task_def["payload"]["image"]
                    if not isinstance(image, dict) or "taskId" not in image:
                        continue

                    task_id = image["taskId"]
                    if task_id in tasks_to_create:
                        continue

                    tasks_to_create[task_id] = [image["path"]]

                # Add private artifacts
                if "MOZ_FETCHES" in task_def["payload"].get("env", {}):
                    fetches = json.loads(
                        task_def["payload"].get("env", {}).get("MOZ_FETCHES", {})
                    )
                    for fetch in fetches:
                        if fetch["artifact"].startswith("public"):
                            continue

                        task_id = fetch["task"]
                        tasks_to_create[task_id].append(fetch["artifact"])

        for task_id, artifacts in tasks_to_create.items():
            new_task = deepcopy(task)
            new_task["label"] = f"firefoxci-artifact-{task['name']}-{task_id}"

            env = new_task["worker"]["env"]
            env["FETCH_FIREFOXCI_TASK_ID"] = task_id
            env["FETCH_FIREFOXCI_ARTIFACTS"] = json.dumps(artifacts)

            artifact_dir = env["MOZ_ARTIFACT_DIR"]
            new_task["worker"]["artifacts"] = []
            for artifact in artifacts:
                name = artifact.rsplit("/", 1)[-1]
                new_task["worker"]["artifacts"].append(
                    {
                        "type": "file",
                        "name": artifact,
                        "path": f"{artifact_dir}/{name}",
                    }
                )
            yield new_task
