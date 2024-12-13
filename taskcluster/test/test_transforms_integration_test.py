# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from pprint import pprint
from typing import Any

import pytest
from taskgraph.util.copy import deepcopy
from taskgraph.util.templates import merge

from fxci_config_taskgraph.transforms.integration_test import transforms
from fxci_config_taskgraph.util.integration import FIREFOXCI_ROOT_URL, find_tasks


@pytest.fixture
def run_test(run_transform, responses):
    """This fixture returns a function that will execute the test.

    Input to the function is a JSON object representing extra task config of a
    single task that will be found on the index.

    The fixture will return the result of running the `integration_test`
    transforms on this task.
    """
    index = "foo.bar.baz"
    decision_task_id = "abc"

    task_label = "foo"
    base_task = {
        "attributes": {},
        "task": {
            "dependencies": [],
            "extra": {},
            "metadata": {"name": task_label, "description": "test"},
            "payload": {"command": ""},
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

        result = run_transform(transforms, {"decision-index-paths": [index]})
        if not result:
            return None

        assert len(result) == 1
        result = result[0]
        print("Dumping for copy/paste:")
        pprint(result, indent=2)
        return result

    return inner


def test_no_unittest_variant_skipped(run_test):
    assert run_test({"attributes": {"foo": "bar"}}) is None


def test_wrong_unittest_variant_skipped(run_test):
    assert run_test({"attributes": {"unittest_variant": "something-else"}}) is None


def test_macosx_skipped(run_test):
    assert (
        run_test(
            {
                "attributes": {
                    "unittest_variant": "os-integration",
                    "test_platform": "macosx1100",
                }
            }
        )
        is None
    )


def test_android_hw_skipped(run_test):
    assert (
        run_test(
            {
                "attributes": {
                    "unittest_variant": "os-integration",
                    "test_platform": "android-hw-4.0",
                }
            }
        )
        is None
    )


def test_basic(run_test):
    result = run_test({"attributes": {"unittest_variant": "os-integration"}})
    assert result == {
        "attributes": {"integration": "gecko"},
        "dependencies": {"apply": "tc-admin-apply-staging"},
        "description": "test",
        "label": "gecko-foo",
        "task": {
            "extra": {},
            "metadata": {"description": "test", "name": "gecko-foo"},
            "payload": {"command": ""},
            "priority": "low",
            "routes": ["checks"],
            "schedulerId": "ci-level-1",
            "tags": {},
            "taskGroupId": "abc",
        },
    }


def test_docker_image(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {"payload": {"image": {"taskId": "def"}}},
        }
    )
    assert result["dependencies"] == {
        "apply": "tc-admin-apply-staging",
        "docker-image": "firefoxci-artifact-gecko-def",
    }
    assert result["task"]["payload"].get("image") == {
        "path": "public/image.tar.zst",
        "taskId": {"task-reference": "<docker-image>"},
        "type": "task-image",
    }


def test_public_fetch_generic_worker(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "command": [["chmod", "+x", "run-task"], ["cmd"]],
                    "env": {
                        "MOZ_FETCHES": '[{"task": "def", "artifact": "public/foo.txt"}]'
                    },
                },
                "tags": {"worker-implementation": "generic-worker"},
            },
        }
    )
    assert result["dependencies"] == {"apply": "tc-admin-apply-staging"}
    assert result["task"]["payload"]["command"] == [
        ["chmod", "+x", "run-task"],
        [
            "bash",
            "-c",
            "TASKCLUSTER_ROOT_URL=https://firefox-ci-tc.services.mozilla.com cmd",
        ],
    ]


def test_public_fetch_generic_worker_windows(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "command": ["cmd"],
                    "env": {
                        "MOZ_FETCHES": '[{"task": "def", "artifact": "public/foo.txt"}]'
                    },
                },
                "tags": {"os": "windows", "worker-implementation": "generic-worker"},
            },
        }
    )
    assert result["dependencies"] == {"apply": "tc-admin-apply-staging"}
    assert result["task"]["payload"]["command"] == [
        'set "TASKCLUSTER_ROOT_URL=https://firefox-ci-tc.services.mozilla.com" & cmd'
    ]


def test_public_fetch_docker_worker(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "command": ["cmd"],
                    "env": {
                        "MOZ_FETCHES": '[{"task": "def", "artifact": "public/foo.txt"}]'
                    },
                }
            },
        }
    )
    assert result["dependencies"] == {"apply": "tc-admin-apply-staging"}
    assert result["task"]["payload"]["command"] == [
        "bash",
        "-c",
        "TASKCLUSTER_ROOT_URL=https://firefox-ci-tc.services.mozilla.com " "cmd",
    ]


def test_private_artifact(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "command": ["cmd"],
                    "env": {"MOZ_FETCHES": '[{"task": "def", "artifact": "foo.txt"}]'},
                }
            },
        }
    )
    assert result["dependencies"] == {
        "apply": "tc-admin-apply-staging",
        "fetch-def": "firefoxci-artifact-gecko-def",
    }
    assert result["task"]["payload"]["env"]["MOZ_FETCHES"] == {
        "task-reference": '[{"task": "<fetch-def>", "artifact": "foo.txt"}]'
    }


def test_mounts_task_id(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "mounts": [
                        {"content": {"taskId": "def", "artifact": "public/foo.txt"}}
                    ]
                }
            },
        }
    )
    assert result["task"]["payload"]["mounts"] == [
        {
            "content": {
                "url": "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/def/artifacts/public/foo.txt"
            }
        }
    ]


def test_mounts_namespace(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {
                    "mounts": [
                        {
                            "content": {
                                "namespace": "foo.bar.baz",
                                "artifact": "public/foo.txt",
                            }
                        }
                    ]
                }
            },
        }
    )
    assert result["task"]["payload"]["mounts"] == [
        {
            "content": {
                "url": "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/abc/artifacts/public/foo.txt"
            }
        }
    ]


def test_docker_cache(run_test):
    result = run_test(
        {
            "attributes": {"unittest_variant": "os-integration"},
            "task": {
                "payload": {"cache": {"gecko-level-3": "path"}},
                "scopes": ["cache:gecko-level-3"],
            },
        }
    )
    assert result["task"]["payload"]["cache"] == {"ci-level-1": "path"}
    assert result["task"]["scopes"] == ["cache:ci-level-1"]
