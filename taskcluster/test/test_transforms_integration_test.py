# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from pprint import pprint
from typing import Any

import pytest
from taskgraph.util.copy import deepcopy
from taskgraph.util.templates import merge

from fxci_config_taskgraph.transforms.integration_test import transforms
from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL, STAGING_ROOT_URL
from fxci_config_taskgraph.util.integration import find_tasks


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
            "payload": {"command": ""},
            "tags": {},
        },
    }

    responses.add(
        responses.GET,
        f"{FIREFOXCI_ROOT_URL}/api/index/v1/task/{index}",
        json={"taskId": decision_task_id},
    )

    # `name` may seem like an awkard identifier here, but outside of tests
    # this comes from the keys in a `kind`. `task_label` is not really
    # an ideal default, but it's the best option we have here, and this value
    # is irrelevant to many tests anyways.
    def inner(task: dict[str, Any], name: str = task_label) -> dict[str, Any] | None:
        find_tasks.cache_clear()

        task = merge(deepcopy(base_task), task)
        task_graph = {task_label: task}

        responses.upsert(
            responses.GET,
            f"{FIREFOXCI_ROOT_URL}/api/queue/v1/task/{decision_task_id}/artifacts/public%2Ftask-graph.json",
            json=task_graph,
        )

        result = run_transform(
            transforms, {"decision-index-paths": [index], "name": name}
        )
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
    result = run_test({"attributes": {"unittest_variant": "os-integration"}}, "gecko")
    assert result == {
        "attributes": {"integration": "gecko"},
        "dependencies": {"apply": "tc-admin-apply-staging"},
        "description": "test",
        "label": "gecko-foo",
        "optimization": {
            "integration-test": [
                "taskcluster/fxci_config_taskgraph/**",
                "taskcluster/kinds/firefoxci-artifact/kind.yml",
                "taskcluster/kinds/integration-test/kind.yml",
            ],
        },
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
        },
        "gecko",
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
        },
        "gecko",
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
