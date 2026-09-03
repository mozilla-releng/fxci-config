# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import hashlib
from unittest.mock import MagicMock

import aiohttp
import pytest

from ciadmin.generate import in_tree_actions, tcyml
from ciadmin.generate.ciconfig.projects import Project

MAIN = b"tasks:\n  - task: main\n"
RELEASE = b"tasks:\n  - task: release\n"


def git_oid(content):
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def tcyml_hash(content):
    return hashlib.sha256(content).hexdigest()[:10]


GIT_PROJECT = {
    "repo": "https://github.com/mozilla/example",
    "repo_type": "git",
    "trust_domain": "foo",
    "branches": [
        {"name": "main", "level": 3},
        {"name": "release/*", "level": 2},
    ],
    "features": {"taskgraph-actions": True},
}

HG_PROJECT = {
    "repo": "https://hg.mozilla.org/example",
    "repo_type": "hg",
    "access": "scm_level_3",
    "trust_domain": "foo",
    "branches": [{"name": "default"}],
    "features": {"gecko-actions": True, "hg-push": True},
}


@pytest.fixture
def projects(mock_ciconfig_file):
    def mocker(**projects):
        mock_ciconfig_file("projects.yml", projects)

    return mocker


@pytest.fixture
def fake_git(monkeypatch):
    """Stub the two github lookups, recording what they were asked for."""

    def mocker(oids_by_branch, blobs):
        calls = {"oids": [], "blobs": []}

        async def get_blob_oids(repo_path):
            calls["oids"].append(repo_path)
            return oids_by_branch

        async def get_blobs(repo_path, oids):
            calls["blobs"].append((repo_path, set(oids)))
            return {oid: blobs[oid] for oid in oids}

        monkeypatch.setattr(tcyml, "get_blob_oids", get_blob_oids)
        monkeypatch.setattr(tcyml, "get_blobs", get_blobs)
        return calls

    return mocker


# ---------------------------------------------------------------------------
# configured_branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branches,expected",
    (
        pytest.param(
            [{"name": "main", "level": 3}, {"name": "release/*", "level": 2}],
            ["main", "release/*", "main"],
            id="default-branch-appended-even-when-already-listed",
        ),
        # A bare `*` would pull in every branch in the repo.
        pytest.param([{"name": "*", "level": 1}], ["main"], id="bare-star-dropped"),
    ),
)
def test_configured_branches(branches, expected):
    project = Project(
        alias="example", **{**GIT_PROJECT, "branches": branches}, default_branch="main"
    )
    assert in_tree_actions.configured_branches(project) == expected


# ---------------------------------------------------------------------------
# parse_and_hash
# ---------------------------------------------------------------------------


def test_parse_and_hash():
    parsed, digest = in_tree_actions.parse_and_hash(MAIN)
    assert parsed == {"tasks": [{"task": "main"}]}
    assert digest == tcyml_hash(MAIN)


@pytest.mark.parametrize(
    "tcy,why",
    (
        (b"", "some ancient projects have no .taskcluster.yml"),
        (b"\tnot: [valid", "not valid YAML"),
        (b"tasks:\n  $let: {}\n  in: []\n", "tasks is a dict, not a list"),
        (b"other: 1\n", "no tasks key at all"),
        (b"just a string\n", "not a mapping"),
    ),
)
def test_parse_and_hash_skips_files_we_cannot_use(tcy, why):
    assert in_tree_actions.parse_and_hash(tcy) is None, why


# ---------------------------------------------------------------------------
# hash_taskcluster_ymls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_shared_taskcluster_yml_is_only_downloaded_once(projects, fake_git):
    """Branches sharing a `.taskcluster.yml` share its oid, so it costs one fetch."""
    projects(example=GIT_PROJECT)
    calls = fake_git(
        oids_by_branch={
            "main": git_oid(MAIN),
            "release/1": git_oid(MAIN),
            "release/2": git_oid(MAIN),
            "release/3": git_oid(RELEASE),
        },
        blobs={git_oid(MAIN): MAIN, git_oid(RELEASE): RELEASE},
    )

    hashes = await in_tree_actions.hash_taskcluster_ymls()

    # Four branches, two distinct files, one request for both of them.
    assert calls["blobs"] == [("mozilla/example", {git_oid(MAIN), git_oid(RELEASE)})]
    assert set(hashes["example"]) == {"main", "release/1", "release/2", "release/3"}
    for branch in ("main", "release/1", "release/2"):
        assert hashes["example"][branch]["hash"] == tcyml_hash(MAIN)
    assert hashes["example"]["release/3"]["hash"] == tcyml_hash(RELEASE)


@pytest.mark.asyncio
async def test_each_branch_records_its_own_level(projects, fake_git):
    projects(example=GIT_PROJECT)
    fake_git(
        oids_by_branch={"main": git_oid(MAIN), "release/1": git_oid(MAIN)},
        blobs={git_oid(MAIN): MAIN},
    )

    hashes = await in_tree_actions.hash_taskcluster_ymls()

    assert hashes["example"]["main"]["level"] == 3
    assert hashes["example"]["release/1"]["level"] == 2
    assert hashes["example"]["main"]["alias"] == "example"


@pytest.mark.asyncio
async def test_unconfigured_branches_are_ignored(projects, fake_git):
    projects(example=GIT_PROJECT)
    calls = fake_git(
        oids_by_branch={"main": git_oid(MAIN), "some-topic-branch": git_oid(RELEASE)},
        blobs={git_oid(MAIN): MAIN, git_oid(RELEASE): RELEASE},
    )

    hashes = await in_tree_actions.hash_taskcluster_ymls()

    assert set(hashes["example"]) == {"main"}
    # The unconfigured branch's file is never even asked for.
    assert calls["blobs"] == [("mozilla/example", {git_oid(MAIN)})]


@pytest.mark.asyncio
async def test_a_branch_without_a_taskcluster_yml_is_skipped(projects, fake_git):
    """A null oid is how a branch reports having no `.taskcluster.yml`."""
    projects(example=GIT_PROJECT)
    calls = fake_git(
        oids_by_branch={"main": git_oid(MAIN), "release/1": None},
        blobs={git_oid(MAIN): MAIN},
    )

    hashes = await in_tree_actions.hash_taskcluster_ymls()

    assert set(hashes["example"]) == {"main"}
    assert calls["blobs"] == [("mozilla/example", {git_oid(MAIN)})]


@pytest.mark.asyncio
async def test_an_unusable_taskcluster_yml_is_skipped(projects, fake_git):
    projects(example=GIT_PROJECT)
    fake_git(
        oids_by_branch={"main": git_oid(MAIN), "release/1": git_oid(b"nope\n")},
        blobs={git_oid(MAIN): MAIN, git_oid(b"nope\n"): b"nope\n"},
    )

    hashes = await in_tree_actions.hash_taskcluster_ymls()

    assert set(hashes["example"]) == {"main"}


@pytest.mark.asyncio
async def test_a_project_with_no_usable_branches_still_gets_an_entry(
    projects, fake_git
):
    """`update_resources` looks every project up by alias."""
    projects(example=GIT_PROJECT)
    fake_git(oids_by_branch={"release/1": None}, blobs={})

    assert await in_tree_actions.hash_taskcluster_ymls() == {"example": {}}


@pytest.mark.asyncio
async def test_projects_without_actions_are_left_out(projects, fake_git):
    projects(
        example=GIT_PROJECT,
        no_actions={**GIT_PROJECT, "features": {}},
    )
    fake_git(oids_by_branch={"main": git_oid(MAIN)}, blobs={git_oid(MAIN): MAIN})

    hashes = await in_tree_actions.hash_taskcluster_ymls()

    assert set(hashes) == {"example"}


# ---------------------------------------------------------------------------
# hash_taskcluster_ymls, hg projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hg_project(projects, monkeypatch):
    """An hg repo has the one branch, fetched over hg's own API."""
    projects(example=HG_PROJECT)
    asked = []

    async def get(repo_path, repo_type="hg", **kwargs):
        asked.append((repo_path, repo_type, kwargs))
        return MAIN

    monkeypatch.setattr(tcyml, "get", get)

    hashes = await in_tree_actions.hash_taskcluster_ymls()

    # No revision override, so `tcyml.get` resolves the hg "default" branch,
    # which is what the per-branch call it replaced worked out to.
    assert asked == [("https://hg.mozilla.org/example", "hg", {})]
    assert hashes["example"]["default"]["hash"] == tcyml_hash(MAIN)
    assert hashes["example"]["default"]["level"] == 3


@pytest.mark.asyncio
async def test_hg_project_without_a_taskcluster_yml(projects, monkeypatch):
    """A 404 means the project moved the file away to disable Taskcluster."""
    projects(example=HG_PROJECT)

    async def get(repo_path, repo_type="hg", **kwargs):
        raise aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=404)

    monkeypatch.setattr(tcyml, "get", get)

    assert await in_tree_actions.hash_taskcluster_ymls() == {"example": {}}


@pytest.mark.asyncio
async def test_hg_project_propagates_other_errors(projects, monkeypatch):
    projects(example=HG_PROJECT)

    async def get(repo_path, repo_type="hg", **kwargs):
        raise aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=500)

    monkeypatch.setattr(tcyml, "get", get)

    with pytest.raises(aiohttp.ClientResponseError):
        await in_tree_actions.hash_taskcluster_ymls()


@pytest.mark.asyncio
async def test_an_unsupported_repo_type_is_an_error(projects, monkeypatch):
    projects(example={**GIT_PROJECT, "repo_type": "svn"})

    with pytest.raises(Exception, match="unsupported repo type svn"):
        await in_tree_actions.hash_taskcluster_ymls()


@pytest.mark.asyncio
async def test_a_github_failure_aborts_the_whole_run(projects, monkeypatch):
    """Half a picture of the hooks would delete the ones we failed to see."""
    projects(example=GIT_PROJECT)

    async def get_blob_oids(repo_path):
        raise RuntimeError("GraphQL query failed")

    monkeypatch.setattr(tcyml, "get_blob_oids", get_blob_oids)

    with pytest.raises(RuntimeError, match="GraphQL query failed"):
        await in_tree_actions.hash_taskcluster_ymls()


# ---------------------------------------------------------------------------
# invalidates_hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidates_hooks(projects):
    """A configured branch of a configured repo, and the near misses"""
    projects(example=GIT_PROJECT)

    assert await in_tree_actions.invalidates_hooks("mozilla/example", "main")
    assert await in_tree_actions.invalidates_hooks("mozilla/example", "release/1")
    # projects.yml spells one repository `Firefox-AI/firefox-prototypes`, so
    # the push and the config can disagree on case.
    assert await in_tree_actions.invalidates_hooks("Mozilla/Example", "main")

    assert not await in_tree_actions.invalidates_hooks("octocat/hello-world", "main")
    # The repo is configured, but no hook comes from this branch, so a deploy
    # triggered by it would change nothing.
    assert not await in_tree_actions.invalidates_hooks("mozilla/example", "some-topic")


@pytest.mark.asyncio
async def test_invalidates_hooks_ignores_trailing_slash(projects):
    projects(example={**GIT_PROJECT, "repo": "https://github.com/mozilla/example/"})
    assert await in_tree_actions.invalidates_hooks("mozilla/example", "main")


@pytest.mark.asyncio
async def test_invalidates_hooks_ignores_projects_we_do_not_hash(projects):
    """A private repo is configured, but its `.taskcluster.yml` is never fetched."""
    projects(
        example={
            **GIT_PROJECT,
            "features": {"taskgraph-actions": True, "github-private-repo": True},
        }
    )
    assert not await in_tree_actions.invalidates_hooks("mozilla/example", "main")


@pytest.mark.asyncio
async def test_invalidates_hooks_ignores_hg_projects(projects):
    """The pulse message only ever describes a github push."""
    projects(example={**HG_PROJECT, "repo": "https://hg.mozilla.org/mozilla/example"})
    assert not await in_tree_actions.invalidates_hooks("mozilla/example", "default")


@pytest.mark.asyncio
async def test_invalidates_hooks_default_branch_is_always_configured(projects):
    projects(example={**GIT_PROJECT, "branches": [{"name": "*", "level": 1}]})
    assert await in_tree_actions.invalidates_hooks("mozilla/example", "main")
    assert not await in_tree_actions.invalidates_hooks("mozilla/example", "some-topic")
