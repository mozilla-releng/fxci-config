# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re

import pytest
from tcadmin.util.sessions import aiohttp_session, with_aiohttp_session

from ciadmin.generate.ciconfig.projects import Project

_HEAD_REGEX = re.compile(r" symref=HEAD:([^ ]+) ")
_GIT_UPLOAD_PACK_URL = "{repo_base_url}/info/refs?service=git-upload-pack"


async def _get_git_default_branch(project):
    git_url = _GIT_UPLOAD_PACK_URL.format(repo_base_url=project.repo)
    # XXX You must set a git-like user agent otherwise Git http endpoints don't
    # return any data.
    headers = {"User-Agent": "git/mozilla-ci-admin"}
    session = aiohttp_session()
    async with session.get(git_url, headers=headers) as response:
        response.raise_for_status()
        result = await response.text()

    match = _HEAD_REGEX.search(result)
    if match is None:
        raise ValueError(f"{git_url} does not contain data about the default branch")

    remote_branch_name = match.group(1)
    branch_name = remote_branch_name.replace("refs/heads/", "")
    return branch_name


@pytest.mark.asyncio
@with_aiohttp_session
async def check_default_branches_for_git_repos():
    """
    Ensures that the default branch present in the ci-configuration's
    `projects.yml` match the ones from git metadata
    """

    projects = await Project.fetch_all()

    # TODO: find a better flag to filter out private repos
    branches_in_projects = {
        project.alias: project.default_branch
        for project in projects
        if project.repo_type == "git" and "private" not in project.repo
    }
    branches_on_github = {
        project.alias: await _get_git_default_branch(project)
        for project in projects
        if project.repo_type == "git" and "private" not in project.repo
    }
    assert branches_in_projects == branches_on_github
