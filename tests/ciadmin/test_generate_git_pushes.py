# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.appconfig import AppConfig
from tcadmin.resources import Resources

from ciadmin.generate import git_pushes
from ciadmin.generate.ciconfig.projects import Project

SIMPLE_TEMPLATE = {
    "schedulerId": "${trust_domain}-level-${level}",
    "scopes": ["assume:${project_role_prefix}:branch:*"],
}

GIT_PROJECT = Project(
    alias="myproject",
    branches=[
        {"name": "main", "level": 3},
        {"name": "dev", "level": 1},
    ],
    repo="https://github.com/mozilla/myproject",
    repo_type="git",
    trust_domain="foo",
    features={"git-push": {"enabled": True}},
)

PROJECTS_YML = {
    "myproject": {
        "repo": "https://github.com/mozilla/myproject",
        "repo_type": "git",
        "trust_domain": "foo",
        "branches": [{"name": "main", "level": 3}],
        "features": {"git-push": {"enabled": True}},
    },
}


@pytest.fixture(autouse=True)
def appconfig():
    with AppConfig._as_current(AppConfig()):
        yield


@pytest.mark.asyncio
async def test_make_hook(mock_ciconfig_file):
    mock_ciconfig_file("git-push-template.yml", SIMPLE_TEMPLATE)
    hook = await git_pushes.make_hook(GIT_PROJECT, GIT_PROJECT.branches[0])

    assert hook.hookGroupId == "git-push"
    assert hook.hookId == "mozilla/myproject/main"
    assert "assume:repo:github.com/mozilla/myproject:branch:*" in hook.task["scopes"]

    schema = hook.triggerSchema
    assert schema["type"] == "object"
    assert set(schema["required"]) == {
        "sha",
        "base_sha",
        "ref",
        "owner",
    }
    assert set(schema["properties"]) == {
        "sha",
        "base_sha",
        "ref",
        "owner",
        "base_ref",
    }
    assert schema["properties"]["sha"]["pattern"] == "^[0-9a-f]{40}$"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "branch_idx,expected", [(0, "foo-level-3"), (1, "foo-level-1")]
)
async def test_make_hook_scheduler_id(mock_ciconfig_file, branch_idx, expected):
    mock_ciconfig_file("git-push-template.yml", SIMPLE_TEMPLATE)
    hook = await git_pushes.make_hook(GIT_PROJECT, GIT_PROJECT.branches[branch_idx])
    assert hook.task["schedulerId"] == expected


@pytest.mark.asyncio
async def test_update_resources_filters_by_feature(mock_ciconfig_file):
    mock_ciconfig_file("git-push-template.yml", SIMPLE_TEMPLATE)
    mock_ciconfig_file(
        "projects.yml",
        {
            "with-feature": {
                **PROJECTS_YML["myproject"],
                "repo": "https://github.com/mozilla/with-feature",
            },
            "without-feature": {
                **PROJECTS_YML["myproject"],
                "repo": "https://github.com/mozilla/without-feature",
                "features": {},
            },
        },
    )
    r = Resources()
    r.manage("Hook=git-push/.*")
    r.manage("Role=hook-id:git-push/.*")
    await git_pushes.update_resources(r)

    hook_ids = {res.hookId for res in r if hasattr(res, "hookId")}
    assert "mozilla/with-feature/main" in hook_ids
    assert "mozilla/without-feature/main" not in hook_ids


@pytest.mark.asyncio
async def test_update_resources_one_hook_and_role_per_branch(mock_ciconfig_file):
    branches = [{"name": "dev", "level": 1}, {"name": "main", "level": 3}]
    mock_ciconfig_file("git-push-template.yml", SIMPLE_TEMPLATE)
    mock_ciconfig_file(
        "projects.yml",
        {
            "myproject": {
                **PROJECTS_YML["myproject"],
                "branches": branches,
            }
        },
    )
    resources = Resources()
    resources.manage("Hook=git-push/.*")
    resources.manage("Role=hook-id:git-push/.*")
    await git_pushes.update_resources(resources)

    hooks = [r for r in resources if hasattr(r, "hookId")]
    roles = [r for r in resources if hasattr(r, "roleId")]
    assert len(hooks) == 2
    assert len(roles) == 2

    for i, branch in enumerate(branches):
        assert roles[i].roleId == f"hook-id:git-push/mozilla/myproject/{branch['name']}"
        assert set(roles[i].scopes) == {
            f"assume:repo:github.com/mozilla/myproject:branch:{branch['name']}",
            "queue:route:index.git-push.v1.myproject.*",
            "queue:create-task:highest:infra/build-decision",
        }
