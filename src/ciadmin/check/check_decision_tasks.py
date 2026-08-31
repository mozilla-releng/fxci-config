# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
from collections import defaultdict

import pytest
from taskcluster.aio import Auth, Index, Queue
from taskcluster.aio.download import downloadArtifactToBuf
from taskcluster.utils import scopeMatch
from tcadmin.util.scopes import satisfies
from tcadmin.util.sessions import aiohttp_session, with_aiohttp_session

from ciadmin.generate.ciconfig.environment import Environment

PRIORITY_LEVELS = [
    "highest",
    "very-high",
    "high",
    "medium",
    "low",
    "very-low",
    "lowest",
]

# Decision tasks whose full task-graph is used to verify that the currently
# generated grants still satisfy everything the graph creates.
DECISION_TASK_INDEXES = [
    "gecko.v2.mozilla-central.latest.taskgraph.decision",
]


async def _fetch_decision_task(root_url, index_path):
    session = aiohttp_session()
    index = Index({"rootUrl": root_url}, session=session)
    queue = Queue({"rootUrl": root_url}, session=session)

    try:
        index_result = await index.findTask(index_path)
    except Exception as e:
        raise AssertionError(f"Could not resolve index path {index_path!r}") from e
    task_id = index_result["taskId"]

    task = await queue.task(task_id)

    try:
        buf, _ = await downloadArtifactToBuf(
            taskId=task_id, name="public/task-graph.json", queueService=queue
        )
    except Exception as e:
        raise AssertionError(
            "Could not fetch public/task-graph.json for Decision task"
            f"{task_id} ({index_path})"
        ) from e
    task_graph = json.loads(bytes(buf))
    return task, task_graph


def _required_scopes(task, task_graph):
    scheduler_id = task["schedulerId"]

    scopes = defaultdict(set)
    scope_sets = defaultdict(set)

    for label, node in task_graph.items():
        task_def = node["task"]

        for scope in task_def.get("scopes") or []:
            scopes[scope].add(label)
        for route in task_def.get("routes") or []:
            scopes[f"queue:route:{route}"].add(label)
        scopes[f"queue:create-task:project:{task_def.get('projectId', 'none')}"].add(
            label
        )
        scopes[f"queue:scheduler-id:{scheduler_id}"].add(label)

        task_queue_id = task_def.get("taskQueueId") or "{}/{}".format(
            task_def["provisionerId"], task_def["workerType"]
        )
        # A task may be created with a scope for its own priority or any
        # priority above it.
        priority = task_def.get("priority", "lowest")
        priorities = PRIORITY_LEVELS[: PRIORITY_LEVELS.index(priority) + 1]
        priority_scopes = tuple(
            f"queue:create-task:{priority}:{task_queue_id}" for priority in priorities
        )
        scope_sets[priority_scopes].add(label)

    return scopes, scope_sets


@pytest.fixture(scope="module")
async def anonymous_scopes():
    environment = await Environment.current()
    auth = Auth({"rootUrl": environment.root_url})
    role = await auth.role("anonymous")
    return role["expandedScopes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("index_path", DECISION_TASK_INDEXES)
@with_aiohttp_session
async def check_decision_task_scopes(index_path, generated_resolver, anonymous_scopes):
    environment = await Environment.current()
    if environment.name != "firefoxci":
        pytest.skip(f"{environment.name} not supported")

    task, task_graph = await _fetch_decision_task(environment.root_url, index_path)
    granted = generated_resolver.expandScopes(task["scopes"]) + anonymous_scopes

    required_scopes, required_scope_sets = _required_scopes(task, task_graph)

    failures = []
    for scope, labels in sorted(required_scopes.items()):
        if not satisfies(granted, [scope]):
            examples = ", ".join(sorted(labels)[:3])
            failures.append(f"  {scope}\n    needed by: {examples}")

    for scope_set, labels in sorted(required_scope_sets.items()):
        if not scopeMatch(granted, [[s] for s in scope_set]):
            examples = ", ".join(sorted(labels)[:3])
            failures.append(
                f"  one of: {', '.join(scope_set)}\n    needed by: {examples}"
            )

    assert not failures, (
        f"The currently generated grants would fail to satisfy {len(failures)} "
        f"scope(s) required by the task graph created by decision task "
        f"{index_path}:\n" + "\n".join(failures)
    )
