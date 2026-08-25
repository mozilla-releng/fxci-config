# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import attr
import pytest

from ciadmin.generate.ciconfig.projects import Branch, Project


@pytest.mark.asyncio
async def test_fetch_empty(mock_ciconfig_file):
    mock_ciconfig_file("projects.yml", {})
    assert await Project.fetch_all() == []


def _filter_out_parsed_url(attr, *args, **kwargs):
    return attr.name != "_parsed_url"


@pytest.mark.parametrize(
    "project_name,project_data,expected_data,expected_default_branch",
    (
        (
            "ash",
            {
                "repo": "https://hg.mozilla.org/projects/ash",
                "lando_repo": "ash",
                "repo_type": "hg",
                "access": "scm_level_2",
                "trust_domain": "gecko",
                "trust_project": None,
                "branches": [
                    {
                        "name": "default",
                    },
                ],
            },
            {
                "access": "scm_level_2",
                "alias": "ash",
                "branches": [
                    {
                        "name": "default",
                        "level": 2,
                        "cron": False,
                    },
                ],
                "_default_branch": "default",
                "cron": {"targets": []},
                "features": {},
                "is_try": False,
                "lando_repo": "ash",
                "parent_repo": None,
                "repo": "https://hg.mozilla.org/projects/ash",
                "repo_path": "projects/ash",
                "repo_type": "hg",
                "role_prefix": "repo:hg.mozilla.org/projects/ash",
                "trust_domain": "gecko",
                "trust_project": None,
                # defaults
            },
            Branch(name="default", level=2, cron=False),
        ),
        (
            "fenix",
            {
                "repo": "https://github.com/mozilla-mobile/fenix/",
                "repo_type": "git",
                "branches": [
                    {
                        "name": "main",
                        "level": 3,
                    },
                ],
            },
            {
                "access": None,
                "alias": "fenix",
                "branches": [
                    {
                        "name": "main",
                        "level": 3,
                        "cron": False,
                    },
                ],
                "_default_branch": "main",
                "cron": {"targets": []},
                "features": {},
                "is_try": False,
                "lando_repo": None,
                "parent_repo": None,
                "repo": "https://github.com/mozilla-mobile/fenix/",
                "repo_path": "mozilla-mobile/fenix",
                "repo_type": "git",
                "role_prefix": "repo:github.com/mozilla-mobile/fenix",
                "trust_domain": None,
                "trust_project": None,
            },
            Branch(name="main", level=3, cron=False),
        ),
    ),
)
@pytest.mark.asyncio
async def test_fetch_defaults(
    mock_ciconfig_file,
    project_name,
    project_data,
    expected_data,
    expected_default_branch,
):
    "Test a fetch of project data only the required fields, applying defaults"
    mock_ciconfig_file("projects.yml", {project_name: project_data})
    prjs = await Project.fetch_all()
    assert len(prjs) == 1
    project = attr.asdict(prjs[0], filter=_filter_out_parsed_url)
    assert project == expected_data
    assert prjs[0].default_branch == expected_default_branch


@pytest.mark.parametrize(
    "project_name,project_data,expected_data,expected_default_branch",
    (
        (
            "ash",
            {
                "access": "scm_level_2",
                "branches": [
                    {
                        "name": "default",
                    },
                ],
                "cron": {
                    "email_when_trigger_failure": True,
                    "notify_emails": [],
                    "targets": ["a", "b"],
                },
                "features": {
                    "hg-push": {"enabled": True},
                    "taskgraph-cron": {"enabled": False},
                },
                "is_try": True,
                "parent_repo": "https://hg.mozilla.org/mozilla-unified",
                "repo_type": "hg",
                "repo": "https://hg.mozilla.org/projects/ash",
                "trust_domain": "gecko",
                "trust_project": None,
            },
            {
                "access": "scm_level_2",
                "alias": "ash",
                "branches": [
                    {
                        "name": "default",
                        "level": 2,
                        "cron": False,
                    },
                ],
                "cron": {
                    "email_when_trigger_failure": True,
                    "notify_emails": [],
                    "targets": [
                        {"target": "a", "bindings": []},
                        {"target": "b", "bindings": []},
                    ],
                },
                "_default_branch": "default",
                "features": {
                    "hg-push": {"enabled": True},
                    "taskgraph-cron": {"enabled": False},
                },
                "is_try": True,
                "lando_repo": None,
                "parent_repo": "https://hg.mozilla.org/mozilla-unified",
                "repo": "https://hg.mozilla.org/projects/ash",
                "repo_path": "projects/ash",
                "repo_type": "hg",
                "role_prefix": "repo:hg.mozilla.org/projects/ash",
                "trust_domain": "gecko",
                "trust_project": None,
            },
            Branch(name="default", level=2, cron=False),
        ),
        (
            "beetmoverscript",  # git project but not mobile
            {
                "branches": [
                    {
                        "name": "main",
                        "level": 3,
                    },
                ],
                "cron": {
                    "email_when_trigger_failure": True,
                    "notify_emails": [],
                    "targets": ["a", "b"],
                },
                "features": {
                    "hg-push": {"enabled": True},
                    "taskgraph-cron": {"enabled": False},
                },
                "is_try": False,
                "parent_repo": "https://github.com/mozilla-releng/",
                "repo_type": "git",
                "repo": "https://github.com/mozilla-releng/beetmoverscript/",
                "trust_domain": "beet",
                "trust_project": None,
            },
            {
                "access": None,
                "alias": "beetmoverscript",
                "branches": [
                    {
                        "name": "main",
                        "level": 3,
                        "cron": False,
                    },
                ],
                "cron": {
                    "email_when_trigger_failure": True,
                    "notify_emails": [],
                    "targets": [
                        {"target": "a", "bindings": []},
                        {"target": "b", "bindings": []},
                    ],
                },
                "_default_branch": "main",
                "features": {
                    "hg-push": {"enabled": True},
                    "taskgraph-cron": {"enabled": False},
                },
                "is_try": False,
                "lando_repo": None,
                "parent_repo": "https://github.com/mozilla-releng/",
                "repo": "https://github.com/mozilla-releng/beetmoverscript/",
                "repo_path": "mozilla-releng/beetmoverscript",
                "repo_type": "git",
                "role_prefix": "repo:github.com/mozilla-releng/beetmoverscript",
                "trust_domain": "beet",
                "trust_project": None,
            },
            Branch(name="main", level=3, cron=False),
        ),
        (
            "cron-project",  # runs cron on more than one branch
            {
                "branches": [
                    {"name": "main", "level": 3, "cron": True},
                    {"name": "beta", "level": 1, "cron": True},
                ],
                "cron": {
                    "targets": ["a"],
                },
                "features": {
                    "taskgraph-cron": {"enabled": True},
                },
                "repo_type": "git",
                "repo": "https://github.com/mozilla-releng/cron-project",
                "trust_domain": "releng",
            },
            {
                "access": None,
                "alias": "cron-project",
                "branches": [
                    {"name": "main", "level": 3, "cron": True},
                    {"name": "beta", "level": 1, "cron": True},
                ],
                "cron": {
                    "targets": [{"target": "a", "bindings": []}],
                },
                "_default_branch": "main",
                "features": {
                    "taskgraph-cron": {"enabled": True},
                },
                "is_try": False,
                "lando_repo": None,
                "parent_repo": None,
                "repo": "https://github.com/mozilla-releng/cron-project",
                "repo_path": "mozilla-releng/cron-project",
                "repo_type": "git",
                "role_prefix": "repo:github.com/mozilla-releng/cron-project",
                "trust_domain": "releng",
                "trust_project": None,
            },
            Branch(name="main", level=3, cron=True),
        ),
    ),
)
@pytest.mark.asyncio
async def test_fetch_nodefaults(
    mock_ciconfig_file,
    project_name,
    project_data,
    expected_data,
    expected_default_branch,
):
    "Test a fetch of project data with all required fields supplied"
    mock_ciconfig_file("projects.yml", {project_name: project_data})
    prjs = await Project.fetch_all()
    assert len(prjs) == 1
    project = attr.asdict(prjs[0], filter=_filter_out_parsed_url)
    assert project == expected_data
    assert prjs[0].default_branch == expected_default_branch


def test_project_feature():
    "Test the feature method"
    prj = Project(
        alias="prj",
        branches=[{"name": "default"}],
        repo="https://hg.mozilla.org/prj",
        repo_type="hg",
        access="scm_level_3",
        trust_domain="gecko",
        features={
            "taskcluster-pull": True,
            "taskgraph-cron": False,
            "some-data": {"foo": "bar"},
        },
    )
    assert prj.feature("taskcluster-pull")
    assert prj.feature("some-data")
    assert prj.feature("some-data", key="foo") == "bar"
    assert not prj.feature("taskgraph-cron")
    assert not prj.feature("taskgraph-cron")
    assert not prj.feature("buildbot")


def test_project_enabled_features():
    "Test enabled_features"
    prj = Project(
        alias="prj",
        branches=[{"name": "default"}],
        repo="https://hg.mozilla.org/prj",
        repo_type="hg",
        access="scm_level_3",
        trust_domain="gecko",
        features={"taskcluster-pull": True, "taskgraph-cron": False},
    )
    assert prj.enabled_features == ["taskcluster-pull"]


@pytest.mark.parametrize(
    "project_data,expected_branches",
    (
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "default",
                    },
                ],
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_level_3",
                "trust_domain": "gecko",
            },
            [
                Branch(name="default", level=3),
            ],
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "default",
                    },
                ],
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_level_2",
                "trust_domain": "gecko",
            },
            [
                Branch(name="default", level=2),
            ],
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "default",
                    },
                ],
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_level_1",
                "trust_domain": "gecko",
            },
            [
                Branch(name="default", level=1),
            ],
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "default",
                    },
                ],
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_autoland",
                "trust_domain": "gecko",
            },
            [
                Branch(name="default", level=3),
            ],
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "main",
                        "level": 3,
                    },
                ],
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
            },
            [
                Branch(name="main", level=3),
            ],
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "main",
                        "level": 1,
                    },
                ],
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
            },
            [
                Branch(name="main", level=1),
            ],
        ),
    ),
)
def test_project_level_property(project_data, expected_branches):
    "Test the level attribute"
    prj = Project(**project_data)
    assert prj.branches == expected_branches


@pytest.mark.parametrize(
    "project_data,error_type",
    (
        (
            {
                "alias": "prj",
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
                "default_branch": "main",
                "access": 10,
            },
            TypeError,
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "main",
                        "level": "10",
                    },
                ],
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
            },
            TypeError,
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "main",
                        "level": 4,
                    },
                ],
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
            },
            ValueError,
        ),
    ),
)
def test_project_level_failing_validators(project_data, error_type):
    "Test the level attribute"
    with pytest.raises(error_type):
        Project(**project_data)


@pytest.mark.parametrize(
    "project_data,error_type",
    (
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "git",
                "branches": [{"name": "main"}],
            },
            RuntimeError,
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "default",
                        "level": 3,
                    },
                ],
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
            },
            ValueError,
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "default",
                        "level": 3,
                    },
                ],
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_level_3",
            },
            ValueError,
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "default",
                        "level": 3,
                    },
                ],
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "git",
                "access": "scm_level_3",
            },
            ValueError,
        ),
        (
            {
                "alias": "prj",
                "branches": [
                    {
                        "name": "default",
                        "level": 3,
                    },
                ],
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "git",
                "access": "scm_level_3",
            },
            ValueError,
        ),
        (
            # runs cron, but does not say on which branches
            {
                "alias": "prj",
                "branches": [{"name": "main", "level": 3}],
                "repo": "https://github.com/mozilla-releng/prj",
                "repo_type": "git",
                "features": {"taskgraph-cron": True},
            },
            ValueError,
        ),
    ),
)
def test_project_level_failing_post_init_checks(project_data, error_type):
    "Test the level attribute"
    with pytest.raises(error_type):
        Project(**project_data)


def test_project_repo_path_property():
    "Test the repo_path property"
    prj = Project(
        alias="prj",
        branches=[{"name": "default"}],
        repo="https://hg.mozilla.org/a/b/",
        repo_type="hg",
        access="scm_level_3",
        trust_domain="gecko",
    )
    assert prj.repo_path == "a/b"
