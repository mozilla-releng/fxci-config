# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
from pprint import pprint
from typing import Any

import pytest
from taskgraph.util.copy import deepcopy
from taskgraph.util.taskcluster import _get_deps, get_task_definition
from taskgraph.util.taskcluster import _task_definitions_cache
from taskgraph.util.templates import merge

from fxci_config_taskgraph.transforms.firefoxci_artifact import transforms
from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL, STAGING_ROOT_URL
from fxci_config_taskgraph.util.integration import _fetch_task_graph


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
            "provisionerId": "prov",
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

    def inner(
        task: dict[str, Any],
        ancestors: dict[str, Any] = {},
        include_attrs: dict[str, list[str]] = {"unittest_variant": ["os-integration"]},
        exclude_attrs: dict[str, list[str]] = {
            "test_platform": ["android-hw", "macosx"]
        },
        include_deps: list[str] = [],
        mirror_public_fetches: list[str] = [],
        name: str = task_label,
    ) -> dict[str, Any] | None:
        _fetch_task_graph.cache_clear()
        _task_definitions_cache.cache.clear()

        task = merge(deepcopy(base_task), task)
        task_graph = {decision_task_id: task}

        responses.upsert(
            responses.GET,
            f"{FIREFOXCI_ROOT_URL}/api/queue/v1/task/{decision_task_id}/artifacts/public%2Ftask-graph.json",
            json=task_graph,
        )
        if include_deps:
            task_definitions = {decision_task_id: task["task"]}
            task_definitions.update(ancestors)
            def callback(request):
                payload = json.loads(request.body)
                resp_body = {"tasks": [{"taskId": task_id, "task": task_def} for task_id, task_def in task_definitions.items() if task_id in payload["taskIds"]]}
                return 200, [], json.dumps(resp_body)
            responses.add_callback(responses.POST, f"{FIREFOXCI_ROOT_URL}/api/queue/v1/tasks", callback=callback)

        transform_task = {
            "name": name,
            "decision-index-paths": [index],
            "include-attrs": include_attrs,
            "exclude-attrs": exclude_attrs,
            "include-deps": include_deps,
            "mirror-public-fetches": mirror_public_fetches,
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


def test_no_exclude_attr_doesnt_reject_all_tasks(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "image": {
                        "taskId": "abc",
                        "path": "public/build/image.tar.zst",
                    }
                }
            },
        },
        exclude_attrs={},
    )
    assert len(result) == 1


def assert_result(expected_tasks: dict[str, str], prefix, result):
    expected = []
    for task_id, artifact in expected_tasks.items():
        expected.append(
            {
                "cache": {
                    "digest-data": [],
                    "name": f"{prefix}-{task_id}",
                    "type": "firefoxci-artifact.v1",
                },
                "label": f"firefoxci-artifact-{prefix}-{task_id}",
                "name": prefix,
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
        )

    def task_key(task):
        return task["label"]

    result.sort(key=task_key)
    expected.sort(key=task_key)
    assert result == expected


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
        },
        name="gecko",
    )
    assert_result({task_id: artifact}, "gecko", result)


def test_included_public_fetch(run_test):
    task_id = "def"
    artifact = "public/build/foo.zip"
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
        },
        mirror_public_fetches=["^foo"],
        name="gecko",
    )
    assert_result({task_id: artifact}, "gecko", result)


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
        },
        name="gecko",
    )
    assert_result({task_id: artifact}, "gecko", result)


def run_include_deps_test(run_test, *args, **kwargs):
    ancestors = {
        "dep1": {
            "dependencies": [],
            "extra": {},
            "metadata": {"name": "build-thing", "description": "build"},
            "payload": {
                "image": {
                    "taskId": "ghi",
                    "path": "public/image.tar.zst",
                },
            },
            "tags": {},
        },
        "dep2": {
            "dependencies": [
                "dep1",
            ],
            "extra": {},
            "metadata": {"name": "test-thing", "description": "test"},
            "payload": {
                "image": {
                    "taskId": "jkl",
                    "path": "public/image.tar.zst",
                },
            },
            "tags": {},
        },
        "dep3": {
            "dependencies": [
                "dep2",
            ],
            "extra": {},
            "metadata": {"name": "sign-thing", "description": "sign"},
            "payload": {
                "image": {
                    "taskId": "mno",
                    "path": "public/image.tar.zst",
                },
            },
            "tags": {},
        },
    }
    return run_test(*args, ancestors=ancestors, **kwargs)


def test_include_all_deps(run_test):
    task_id = "def"
    artifact = "public/image.tar.zst"
    result = run_include_deps_test(
        run_test,
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "dependencies": [
                    "dep3",
                ],
                "payload": {
                    "image": {
                        "taskId": task_id,
                        "path": artifact,
                    }
                },
            },
        },
        include_deps=["^.*"],
        name="gecko",
    )
    assert_result(
        {task_id: artifact, "ghi": artifact, "jkl": artifact, "mno": artifact},
        "gecko",
        result,
    )


def test_include_some_deps(run_test):
    task_id = "def"
    artifact = "public/image.tar.zst"
    result = run_include_deps_test(
        run_test,
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "dependencies": [
                    "dep3",
                ],
                "payload": {
                    "image": {
                        "taskId": task_id,
                        "path": artifact,
                    }
                },
            },
        },
        include_deps=["^sign", "^test"],
        name="gecko",
    )
    assert_result(
        {task_id: artifact, "jkl": artifact, "mno": artifact}, "gecko", result
    )


def test_no_deps(run_test):
    task_id = "def"
    artifact = "public/image.tar.zst"
    result = run_include_deps_test(
        run_test,
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "dependencies": [
                    "dep3",
                ],
                "payload": {
                    "image": {
                        "taskId": task_id,
                        "path": artifact,
                    }
                },
            },
        },
        include_deps=["^toolchain"],
        name="gecko",
    )
    assert_result({task_id: artifact}, "gecko", result)
