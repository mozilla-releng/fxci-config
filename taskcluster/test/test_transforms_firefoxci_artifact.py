# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from pprint import pprint
from typing import Any

import pytest
from taskgraph.util.copy import deepcopy
from taskgraph.util.templates import merge

from fxci_config_taskgraph.transforms.firefoxci_artifact import transforms
from fxci_config_taskgraph.util.integration import (
    FIREFOXCI_ROOT_URL,
    STAGING_ROOT_URL,
    find_tasks,
)


@pytest.fixture
def run_test(monkeypatch, run_transform, responses):
    """This fixture returns a function that will execute the test.

    Input to the function is a JSON object representing extra task config of a
    single task that will be found on the index.

    The fixture will return the result of running the `integration_test`
    transforms on this task.
    """
    index = "foo.bar.baz"
    decision_task_id = "abc"
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", STAGING_ROOT_URL)
    monkeypatch.setenv("TASK_ID", decision_task_id)

    task_label = "foo"
    base_task = {
        "attributes": {},
        "task": {
            "dependencies": [],
            "extra": {},
            "metadata": {"name": task_label, "description": "test"},
            "payload": {"command": "", "worker": {}},
            "tags": {},
        },
    }

    responses.add(
        responses.GET,
        f"{FIREFOXCI_ROOT_URL}/api/index/v1/task/{index}",
        json={"taskId": decision_task_id},
    )

    def inner(task: dict[str, Any]) -> dict[str, Any] | None:
        find_tasks.cache_clear()

        task = merge(deepcopy(base_task), task)
        task_graph = {task_label: task}

        responses.upsert(
            responses.GET,
            f"{FIREFOXCI_ROOT_URL}/api/queue/v1/task/{decision_task_id}/artifacts/public%2Ftask-graph.json",
            json=task_graph,
        )

        transform_task = {
            "name": "gecko",
            "decision-index-paths": [index],
            "worker": {
                "env": {
                    "MOZ_ARTIFACT_DIR": "/builds/worker/artifacts",
                }
            },
        }
        result = run_transform(transforms, transform_task)
        print("Dumping for copy/paste:")
        pprint(result, indent=2)
        return result

    return inner


def test_no_dependencies(run_test):
    result = run_test({"attributes": {"unittest_variant": "os-integration"}})
    assert result == []


def test_docker_image_no_task_id(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {"payload": {"image": "foo/bar"}},
        }
    )
    assert result == []


def test_public_fetch(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "env": {
                        "MOZ_FETCHES": '[{"task": "def", "artifact": "public/foo.txt"}]'
                    },
                },
            },
        }
    )
    assert result == []


def test_private_fetch_no_attribute(run_test):
    result = run_test(
        {
            "task": {
                "payload": {
                    "env": {
                        "MOZ_FETCHES": '[{"task": "def", "artifact": "private/foo.txt"}]'
                    },
                },
            },
        }
    )
    assert result == []


def assert_result(task_id, artifact, result):
    assert result == [
        {
            "cache": {
                "digest-data": [],
                "name": f"gecko-{task_id}",
                "type": "firefoxci-artifact.v1",
            },
            "label": f"firefoxci-artifact-gecko-{task_id}",
            "name": "gecko",
            "worker": {
                "artifacts": [
                    {
                        "name": artifact,
                        "path": f"/builds/worker/artifacts/{artifact.rsplit('/', 1)[-1]}",
                        "type": "file",
                    }
                ],
                "env": {
                    "FETCH_FIREFOXCI_ARTIFACTS": f'["{artifact}"]',
                    "FETCH_FIREFOXCI_TASK_ID": task_id,
                    "MOZ_ARTIFACT_DIR": "/builds/worker/artifacts",
                },
            },
        }
    ]


def test_private_fetch(run_test):
    task_id = "def"
    artifact = "private/foo.txt"
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "env": {
                        "MOZ_FETCHES": f'[{{"task": "{task_id}", "artifact": "{artifact}"}}]'
                    },
                },
            },
        }
    )
    assert_result(task_id, artifact, result)


def test_docker_image_task_id(run_test):
    task_id = "def"
    artifact = "public/image.tar.zst"
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "image": {
                        "taskId": task_id,
                        "path": artifact,
                    }
                }
            },
        }
    )
    assert_result(task_id, artifact, result)
