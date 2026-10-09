# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.resources import Resources

from ciadmin.generate.ciconfig.projects import Project
from ciadmin.generate.clients import add_scriptworker_client_scopes, update_resources


def make_project(alias, repo, trust_domain, features, level=3):
    return Project(
        alias=alias,
        repo=repo,
        repo_type="git",
        trust_domain=trust_domain,
        branches=[{"name": "main", "level": level}],
        features=features,
    )


PROJECTS = [
    make_project(
        "a", "https://github.com/o/a", "gecko", {"scriptworker-beetmover": True}
    ),
    make_project(
        "b", "https://github.com/o/b", "gecko", {"scriptworker-signing": True}
    ),
    make_project(
        "c", "https://github.com/o/c", "mobile", {"scriptworker-beetmover": True}
    ),
    make_project(
        "d", "https://github.com/o/d", "gecko", {"scriptworker-beetmover": False}
    ),
]


def test_add_scriptworker_client_scopes():
    client_id = "project/releng/scriptworker/v2/beetmover/prod/firefoxci-gecko-3"
    scopes = ["foo"]
    add_scriptworker_client_scopes(scopes, client_id, PROJECTS)
    assert scopes == ["foo", "auth:github-repo-token:read/o/a:*"]


def test_add_scriptworker_client_scopes_t_suffix():
    client_id = "project/releng/scriptworker/v2/beetmover/prod/firefoxci-gecko-t"
    scopes = []
    add_scriptworker_client_scopes(scopes, client_id, PROJECTS)
    assert scopes == ["auth:github-repo-token:read/o/a:*"]


def test_add_scriptworker_client_scopes_level():
    projects = [
        make_project(
            "l1",
            "https://github.com/o/l1",
            "gecko",
            {"scriptworker-beetmover": True},
            level=1,
        ),
        make_project(
            "l3",
            "https://github.com/o/l3",
            "gecko",
            {"scriptworker-beetmover": True},
        ),
    ]
    prefix = "project/releng/scriptworker/v2/beetmover/prod/firefoxci-gecko-"

    scopes = []
    add_scriptworker_client_scopes(scopes, prefix + "3", projects)
    assert scopes == ["auth:github-repo-token:read/o/l3:*"]

    for suffix in ("1", "t"):
        scopes = []
        add_scriptworker_client_scopes(scopes, prefix + suffix, projects)
        assert scopes == [
            "auth:github-repo-token:read/o/l1:*",
            "auth:github-repo-token:read/o/l3:*",
        ]


def test_add_scriptworker_client_scopes_not_scriptworker():
    scopes = ["foo"]
    add_scriptworker_client_scopes(scopes, "project/releng/other", PROJECTS)
    assert scopes == ["foo"]


@pytest.mark.asyncio
async def test_update_resources(mock_ciconfig_file, set_environment):
    mock_ciconfig_file(
        "clients.yml",
        {
            "project/releng/scriptworker/v2/signing/prod/firefoxci-gecko-3": {
                "description": "",
                "scopes": ["queue:claim-work:foo"],
            },
            "project/releng/other": {"description": "", "scopes": ["foo"]},
        },
    )
    mock_ciconfig_file("clients-interpreted.yml", [])
    mock_ciconfig_file(
        "projects.yml",
        {
            "a": {
                "repo": "https://github.com/o/a",
                "repo_type": "git",
                "trust_domain": "gecko",
                "branches": [{"name": "main", "level": 3}],
                "features": {"scriptworker-signing": True},
            },
        },
    )
    resources = Resources([], ["Client=.*"])
    with set_environment("firefoxci"):
        await update_resources(resources)
    scopes = {r.clientId: list(r.scopes) for r in resources}
    assert scopes == {
        "project/releng/scriptworker/v2/signing/prod/firefoxci-gecko-3": [
            "auth:github-repo-token:read/o/a:*",
            "queue:claim-work:foo",
        ],
        "project/releng/other": ["foo"],
    }
