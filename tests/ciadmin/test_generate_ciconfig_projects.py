# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import attr
import pytest

from ciadmin.generate.ciconfig.projects import Project


@pytest.mark.asyncio
async def test_fetch_empty(mock_ciconfig_file):
    mock_ciconfig_file("projects.yml", {})
    assert await Project.fetch_all() == []


def _filter_out_parsed_url(attr, *args, **kwargs):
    return attr.name != "_parsed_url"


@pytest.mark.parametrize(
    "project_name,project_data,expected_data",
    (
        (
            "ash",
            {
                "repo": "https://hg.mozilla.org/projects/ash",
                "repo_type": "hg",
                "access": "scm_level_2",
                "trust_domain": "gecko",
                "trust_project": None,
                "default_branch": "default",
            },
            {
                "_level": None,
                "access": "scm_level_2",
                "alias": "ash",
                "cron": {"targets": []},
                "default_branch": "default",
                "features": {},
                "is_try": False,
                "parent_repo": None,
                "repo": "https://hg.mozilla.org/projects/ash",
                "repo_path": "projects/ash",
                "repo_type": "hg",
                "role_prefix": "repo:hg.mozilla.org/projects/ash",
                "taskcluster_yml_project": None,
                "trust_domain": "gecko",
                "trust_project": None,
                # defaults
            },
        ),
        (
            "fenix",
            {
                "repo": "https://github.com/mozilla-mobile/fenix/",
                "repo_type": "git",
                "level": 3,
            },
            {
                "_level": 3,
                "access": None,
                "alias": "fenix",
                "cron": {"targets": []},
                "default_branch": "main",
                "features": {},
                "is_try": False,
                "parent_repo": None,
                "repo": "https://github.com/mozilla-mobile/fenix/",
                "repo_path": "mozilla-mobile/fenix",
                "repo_type": "git",
                "role_prefix": "repo:github.com/mozilla-mobile/fenix",
                "taskcluster_yml_project": None,
                "trust_domain": None,
                "trust_project": None,
            },
        ),
    ),
)
@pytest.mark.asyncio
async def test_fetch_defaults(
    mock_ciconfig_file, project_name, project_data, expected_data
):
    "Test a fetch of project data only the required fields, applying defaults"
    mock_ciconfig_file("projects.yml", {project_name: project_data})
    prjs = await Project.fetch_all()
    assert len(prjs) == 1
    project = attr.asdict(prjs[0], filter=_filter_out_parsed_url)
    assert project == expected_data


@pytest.mark.parametrize(
    "project_name,project_data,expected_data",
    (
        (
            "ash",
            {
                "access": "scm_level_2",
                "cron": {
                    "email_when_trigger_failure": True,
                    "notify_emails": [],
                    "targets": ["a", "b"],
                },
                "default_branch": "default",
                "features": {
                    "hg-push": {"enabled": True},
                    "gecko-cron": {"enabled": False},
                },
                "is_try": True,
                "parent_repo": "https://hg.mozilla.org/mozilla-unified",
                "repo_type": "hg",
                "repo": "https://hg.mozilla.org/projects/ash",
                "trust_domain": "gecko",
                "trust_project": None,
            },
            {
                "_level": None,
                "access": "scm_level_2",
                "alias": "ash",
                "cron": {
                    "email_when_trigger_failure": True,
                    "notify_emails": [],
                    "targets": [
                        {"target": "a", "bindings": []},
                        {"target": "b", "bindings": []},
                    ],
                },
                "default_branch": "default",
                "features": {
                    "hg-push": {"enabled": True},
                    "gecko-cron": {"enabled": False},
                },
                "is_try": True,
                "parent_repo": "https://hg.mozilla.org/mozilla-unified",
                "repo": "https://hg.mozilla.org/projects/ash",
                "repo_path": "projects/ash",
                "repo_type": "hg",
                "role_prefix": "repo:hg.mozilla.org/projects/ash",
                "taskcluster_yml_project": None,
                "trust_domain": "gecko",
                "trust_project": None,
            },
        ),
        (
            "beetmoverscript",  # git project but not mobile
            {
                "cron": {
                    "email_when_trigger_failure": True,
                    "notify_emails": [],
                    "targets": ["a", "b"],
                },
                "default_branch": "main",
                "features": {
                    "hg-push": {"enabled": True},
                    "gecko-cron": {"enabled": False},
                },
                "is_try": False,
                "level": 3,
                "parent_repo": "https://github.com/mozilla-releng/",
                "repo_type": "git",
                "repo": "https://github.com/mozilla-releng/beetmoverscript/",
                "trust_domain": "beet",
                "trust_project": None,
            },
            {
                "_level": 3,
                "access": None,
                "alias": "beetmoverscript",
                "cron": {
                    "email_when_trigger_failure": True,
                    "notify_emails": [],
                    "targets": [
                        {"target": "a", "bindings": []},
                        {"target": "b", "bindings": []},
                    ],
                },
                "default_branch": "main",
                "features": {
                    "hg-push": {"enabled": True},
                    "gecko-cron": {"enabled": False},
                },
                "is_try": False,
                "parent_repo": "https://github.com/mozilla-releng/",
                "repo": "https://github.com/mozilla-releng/beetmoverscript/",
                "repo_path": "mozilla-releng/beetmoverscript",
                "repo_type": "git",
                "role_prefix": "repo:github.com/mozilla-releng/beetmoverscript",
                "taskcluster_yml_project": None,
                "trust_domain": "beet",
                "trust_project": None,
            },
        ),
    ),
)
@pytest.mark.asyncio
async def test_fetch_nodefaults(
    mock_ciconfig_file, project_name, project_data, expected_data
):
    "Test a fetch of project data with all required fields supplied"
    mock_ciconfig_file("projects.yml", {project_name: project_data})
    prjs = await Project.fetch_all()
    assert len(prjs) == 1
    project = attr.asdict(prjs[0], filter=_filter_out_parsed_url)
    assert project == expected_data


def test_project_feature():
    "Test the feature method"
    prj = Project(
        alias="prj",
        repo="https://hg.mozilla.org/prj",
        repo_type="hg",
        access="scm_level_3",
        trust_domain="gecko",
        features={
            "taskcluster-pull": True,
            "gecko-cron": False,
            "some-data": {"foo": "bar"},
        },
    )
    assert prj.feature("taskcluster-pull")
    assert prj.feature("some-data")
    assert prj.feature("some-data", key="foo") == "bar"
    assert not prj.feature("gecko-cron")
    assert not prj.feature("gecko-cron")
    assert not prj.feature("buildbot")


def test_project_enabled_features():
    "Test enabled_features"
    prj = Project(
        alias="prj",
        repo="https://hg.mozilla.org/prj",
        repo_type="hg",
        access="scm_level_3",
        trust_domain="gecko",
        features={"taskcluster-pull": True, "gecko-cron": False},
    )
    assert prj.enabled_features == ["taskcluster-pull"]


@pytest.mark.parametrize(
    "project_data,expected_level",
    (
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_level_3",
                "trust_domain": "gecko",
            },
            3,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_level_2",
                "trust_domain": "gecko",
            },
            2,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_level_1",
                "trust_domain": "gecko",
            },
            1,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_autoland",
                "trust_domain": "gecko",
            },
            3,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
                "level": 3,
            },
            3,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
                "level": 1,
            },
            1,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
                "level": 1,
            },
            1,
        ),
    ),
)
def test_project_level_property(project_data, expected_level):
    "Test the level attribute"
    prj = Project(**project_data)
    assert prj.level == expected_level


@pytest.mark.parametrize(
    "project_data,error_type",
    (
        (
            {
                "alias": "prj",
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
                "access": 10,
            },
            TypeError,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
                "level": "10",
            },
            TypeError,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://github.com/some-owner/prj",
                "repo_type": "git",
                "level": 4,
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
            {"alias": "prj", "repo": "https://hg.mozilla.org/prj", "repo_type": "git"},
            RuntimeError,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "level": 3,
            },
            ValueError,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_level_3",
                "level": 3,
            },
            ValueError,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "git",
                "access": "scm_level_3",
            },
            ValueError,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "git",
                "access": "scm_level_3",
                "level": 3,
            },
            ValueError,
        ),
        (
            {
                "alias": "prj",
                "repo": "https://hg.mozilla.org/prj",
                "repo_type": "hg",
                "access": "scm_mobile???",
            },
            RuntimeError,
        ),
    ),
)
def test_project_level_failing_post_init_checks(project_data, error_type):
    "Test the level attribute"
    with pytest.raises(error_type):
        prj = Project(**project_data)
        prj.level


def test_project_repo_path_property():
    "Test the repo_path property"
    prj = Project(
        alias="prj",
        repo="https://hg.mozilla.org/a/b/",
        repo_type="hg",
        access="scm_level_3",
        trust_domain="gecko",
    )
    assert prj.repo_path == "a/b"


@pytest.mark.parametrize(
    "repo_type, repo, expected_result",
    (
        ("hg", "https://hg.mozilla.org/prj", "default"),
        ("git", "https://github.com/someowner/somerepo", "main"),
    ),
)
def test_project_branch_property(repo_type, repo, expected_result):
    prj = Project(
        alias="prj",
        repo=repo,
        repo_type=repo_type,
        access="scm_level_3" if repo_type == "hg" else None,
        level=None if repo_type == "hg" else 3,
        trust_domain="gecko",
    )
    assert prj.default_branch == expected_result


def test_project_set_branch_property():
    prj = Project(
        alias="prj",
        repo="https://github.com/someowner/somerepo",
        repo_type="git",
        access=None,
        level=3,
        trust_domain="gecko",
        default_branch="master",
    )
    assert prj.default_branch == "master"
