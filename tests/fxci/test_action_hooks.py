# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import hashlib
import json

import pytest
from tcadmin.appconfig import AppConfig

from ciadmin.generate import tcyml
from ciadmin.generate.ciconfig import get
from fxci import action_hooks

MAIN = b"tasks:\n  - task: main\n"

HG_PROJECT = {
    "repo": "https://hg.mozilla.org/example",
    "repo_type": "hg",
    "access": "scm_level_3",
    "trust_domain": "foo",
    "branches": [{"name": "default"}],
    "features": {"gecko-actions": True, "hg-push": True},
}


def tcyml_hash(content):
    return hashlib.sha256(content).hexdigest()[:10]


@pytest.fixture
def mock_ciconfig_file():
    def mocker(filename, content):
        get._cache[filename] = content

    yield mocker
    get._cache.clear()


@pytest.fixture
def projects(mock_ciconfig_file):
    def mocker(**projects):
        mock_ciconfig_file("projects.yml", projects)

    return mocker


@pytest.fixture
def appconfig():
    with AppConfig._as_current(AppConfig()):
        yield


TRY_PROJECT = {**HG_PROJECT, "access": "scm_level_1", "is_try": True}
REVISION = "abc123"


@pytest.fixture
def actions(mock_ciconfig_file):
    mock_ciconfig_file(
        "actions.yml",
        [
            {"trust_domain": "foo", "levels": [1, 3], "action_perms": ["generic"]},
            {"trust_domain": "bar", "levels": [1], "action_perms": ["generic"]},
        ],
    )


@pytest.fixture
def decision_task(monkeypatch):
    """Stub the decision task and the `.taskcluster.yml` it was made from."""

    def mocker(scopes, tcy=MAIN, expected_hash=None):
        asked = []

        async def fetch_task(task_id):
            return {"scopes": scopes}

        async def fetch_artifact(task_id, name):
            if name == "public/parameters.yml":
                return f"head_rev: {REVISION}\n".encode()
            hook_id = f"in-tree-action-1-generic/{expected_hash or tcyml_hash(tcy)}"
            return json.dumps(
                {"actions": [{"kind": "hook", "hookId": hook_id}]}
            ).encode()

        async def get(repo_path, repo_type="hg", **kwargs):
            asked.append((repo_path, repo_type, kwargs))
            return tcy

        monkeypatch.setattr(action_hooks, "_fetch_task", fetch_task)
        monkeypatch.setattr(action_hooks, "_fetch_artifact", fetch_artifact)
        monkeypatch.setattr(tcyml, "get", get)
        return asked

    return mocker


@pytest.mark.asyncio
async def test_make_decision_task_hooks(projects, actions, decision_task, appconfig):
    """Only actions in the project's trust domain, at or below its level."""
    projects(example=TRY_PROJECT)
    asked = decision_task(["assume:repo:hg.mozilla.org/example:branch:default"])

    hooks = await action_hooks.make_decision_task_hooks("TASKID")

    assert asked == [("https://hg.mozilla.org/example", "hg", {"revision": REVISION})]
    assert [h.id for h in hooks] == [
        f"Hook=project-foo/in-tree-action-1-generic/{tcyml_hash(MAIN)}"
    ]
    assert "example, branch: 'default'" in hooks[0].description


@pytest.mark.asyncio
async def test_make_decision_task_hooks_level_comes_from_config(
    projects, actions, decision_task, appconfig
):
    """A level 3 branch gets hooks at every level up to 3."""
    projects(example=HG_PROJECT)
    decision_task(["assume:repo:hg.mozilla.org/example:branch:default"])

    hooks = await action_hooks.make_decision_task_hooks("TASKID")

    assert [h.hookId.split("/")[0] for h in hooks] == [
        "in-tree-action-1-generic",
        "in-tree-action-3-generic",
    ]


@pytest.mark.asyncio
async def test_make_decision_task_hooks_cron(
    projects, actions, decision_task, appconfig
):
    projects(example=HG_PROJECT)
    decision_task(["assume:repo:hg.mozilla.org/example:cron:nightly"])

    hooks = await action_hooks.make_decision_task_hooks("TASKID")

    assert len(hooks) == 2


@pytest.mark.parametrize(
    "project,scopes,expected_hash,match",
    (
        pytest.param(
            TRY_PROJECT,
            ["assume:repo:hg.mozilla.org/example:pull-request"],
            None,
            "could not find",
            id="pull-request",
        ),
        pytest.param(
            TRY_PROJECT,
            ["assume:repo:hg.mozilla.org/other:branch:default"],
            None,
            "could not find",
            id="unknown-repo",
        ),
        pytest.param(
            {**TRY_PROJECT, "features": {}},
            ["assume:repo:hg.mozilla.org/example:branch:default"],
            None,
            "does not support",
            id="no-actions",
        ),
        pytest.param(
            TRY_PROJECT,
            ["assume:repo:hg.mozilla.org/example:branch:default"],
            "0123456789",
            "but the decision task expects",
            id="hash-mismatch",
        ),
    ),
)
@pytest.mark.asyncio
async def test_make_decision_task_hooks_rejects(
    projects, actions, decision_task, project, scopes, expected_hash, match
):
    projects(example=project)
    decision_task(scopes, expected_hash=expected_hash)
    with pytest.raises(ValueError, match=match):
        await action_hooks.make_decision_task_hooks("TASKID")
