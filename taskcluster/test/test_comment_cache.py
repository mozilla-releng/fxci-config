# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import shlex
from pathlib import Path
from types import SimpleNamespace

import jsone
import pytest
import yaml
from taskgraph.util.cached_tasks import add_optimization


@pytest.mark.parametrize(
    "tasks_for", ["github-issue-comment", "github-pull-request", "github-push"]
)
def test_decision_cache_routes(tasks_for):
    repo = {
        "html_url": "https://github.com/mozilla-releng/fxci-config",
        "name": "fxci-config",
        "full_name": "mozilla-releng/fxci-config",
    }
    event = {
        "action": "created" if tasks_for == "github-issue-comment" else "opened",
        "taskcluster_comment": "integration",
        "pull_request": {
            "user": {"login": "tester"},
            "base": {"repo": repo, "ref": "main", "sha": "a" * 40},
            "head": {"repo": repo, "ref": "test", "sha": "b" * 40},
        },
        "repository": repo,
        "pusher": {"email": "tester@example.com"},
        "ref": "refs/heads/main",
        "before": "a" * 40,
        "after": "b" * 40,
        "base_ref": None,
    }
    template = yaml.safe_load(
        (Path(__file__).parents[2] / ".taskcluster.yml").read_text()
    )
    rendered = jsone.render(
        template,
        {
            "tasks_for": tasks_for,
            "event": event,
            "taskcluster_root_url": "https://stage.taskcluster.nonprod.webservices.mozgcp.net"
            if tasks_for == "github-issue-comment"
            else "https://firefox-ci-tc.services.mozilla.com",
            "as_slugid": lambda name: "test-task-id",
        },
    )
    task = rendered["tasks"][0]
    args = shlex.split(task["payload"]["command"][-1])
    generated_tasks_for = next(
        arg.split("=", 1)[1] for arg in args if arg.startswith("--tasks-for=")
    )
    if tasks_for == "github-issue-comment":
        assert "--target-tasks-method=integration" in args
        assert task["extra"]["tasks_for"] == "github-issue-comment"
    desc = {"attributes": {}}
    add_optimization(
        SimpleNamespace(
            params={
                "tasks_for": generated_tasks_for,
                "level": "1",
                "head_ref": "test",
                "build_date": 0,
            },
            graph_config={"trust-domain": "releng", "taskgraph": {}},
        ),
        desc,
        "docker-images.v2",
        "build-decision",
        digest="test-digest",
    )
    if tasks_for == "github-push":
        assert all(
            route.startswith("index.releng.cache.level-1.") for route in desc["routes"]
        )
    else:
        assert desc["routes"] == [
            "index.releng.cache.pr.docker-images.v2.build-decision.hash.test-digest"
        ]
