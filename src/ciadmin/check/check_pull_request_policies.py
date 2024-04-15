# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
import yaml
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.generate import tcyml
from ciadmin.generate.ciconfig.projects import Project


async def _get_pull_request_policy(project):
    config = yaml.safe_load(
        await tcyml.get(
            project.repo,
            repo_type=project.repo_type,
            revision=None,
            default_branch=project.default_branch,
        )
    )
    return config.get("policy", {}).get("pullRequests")


@pytest.mark.asyncio
@with_aiohttp_session
async def check_pull_request_policies_for_git_repos():
    """Ensures that the pull-request policy defined in projects.yml
    matches the one in-repo.
    """
    skip = (
        "occ",  # tc.yml v0
        "firefox-profiler",  # not landed yet
        "fx-desktop-qa-automation",  # not landed yet
    )

    projects = [p for p in await Project.fetch_all() if not p.repo.endswith("*")]

    def filter_project(p):
        # TODO: find a better flag to filter out private repos
        return (
            p.repo_type == "git"
            and "private" not in p.repo
            and p.feature("github-pull-request")
            and p.alias not in skip
        )

    pr_policies = {
        project.alias: project.feature("github-pull-request", key="policy")
        for project in projects
        if filter_project(project)
    }
    github_pr_policies = {
        project.alias: await _get_pull_request_policy(project)
        for project in projects
        if filter_project(project)
    }
    assert pr_policies == github_pr_policies
