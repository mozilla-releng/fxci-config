# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import aiohttp
import pytest
import yaml
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.generate import tcyml
from ciadmin.generate.ciconfig.projects import Project
from ciadmin.util import github

# A project whose `.taskcluster.yml` this run cannot reach.
UNREADABLE = object()


async def _get_pull_request_policy(project):
    try:
        raw = await tcyml.get(
            project.repo,
            repo_type=project.repo_type,
            revision=None,
            default_branch=project.default_branch.name,
        )
    except aiohttp.ClientResponseError as e:
        # A private repo the auth service would not mint a token for answers
        # exactly like one that is not there. Its policy goes unchecked rather
        # than failing a run that was never going to see the file.
        if e.status == 404 and project.feature("github-private-repo"):
            return UNREADABLE
        raise

    config = yaml.safe_load(raw)
    return config.get("policy", {}).get("pullRequests")


@pytest.mark.asyncio
@with_aiohttp_session
async def check_pull_request_policies_for_git_repos():
    """Ensures that the pull-request policy defined in projects.yml
    matches the one in-repo.
    """
    skip = (
        "occ",  # tc.yml v0
        "fx-desktop-qa-automation",  # not landed yet
        "neqo",  # not landed yet
    )

    projects = [p for p in await Project.fetch_all() if not p.repo.endswith("*")]

    def filter_project(p):
        return (
            p.repo_type == "git"
            and p.feature("github-pull-request")
            and p.alias not in skip
        )

    try:
        readable = {}
        for project in filter(filter_project, projects):
            policy = await _get_pull_request_policy(project)
            if policy is not UNREADABLE:
                readable[project.alias] = (project, policy)
    finally:
        await github.close_clients()

    pr_policies = {
        alias: project.feature("github-pull-request", key="policy")
        for alias, (project, _) in readable.items()
    }
    github_pr_policies = {alias: policy for alias, (_, policy) in readable.items()}
    assert pr_policies == github_pr_policies
