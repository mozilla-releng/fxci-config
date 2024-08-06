# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json

import pytest
from tcadmin.util.sessions import aiohttp_session, with_aiohttp_session

from ciadmin.generate.ciconfig.projects import Project


async def get_hg_repo_owner(project):
    """
    Fetches the repo owner, in the form of unix group, from the
    hg.mozilla.org metadata
    """

    assert (
        project.repo_type == "hg"
    ), "Only hg repos can be queried for group_owner metadata"

    session = aiohttp_session()
    async with session.get(f"{project.repo}/json-repoinfo") as response:
        response.raise_for_status()
        result = await response.read()
    owner = json.loads(result)["group_owner"]
    # Scriptworker doesn't know to convert these named scm levels to `3`.
    if owner in ("scm_allow_direct_push", "scm_autoland"):
        owner = "scm_level_3"

    return owner


@pytest.mark.asyncio
@with_aiohttp_session
async def check_scopes_for_hg_repos():
    """
    Ensures that the access levels present in the ci-configuration's
    `projects.yml` match the ones from hg.mozilla.org metadata
    """

    projects = await Project.fetch_all()
    tc_levels = {
        project.alias: project.access for project in projects if project.access
    }
    hgmo_levels = {
        project.alias: await get_hg_repo_owner(project)
        for project in projects
        if project.repo_type == "hg"
    }
    assert tc_levels == hgmo_levels


@pytest.mark.asyncio
async def check_elevated_privileges_for_staging_repos():
    """
    Ensures that the any project with an alias starting with `staging-`
    has a level of 1 or None.
    """

    projects = await Project.fetch_all()
    elevated_staging_repos = {}
    for project in projects:
        if not project.alias.startswith("staging-"):
            continue

        for branch in project.branches:
            if branch.level not in (1, None):
                elevated_staging_repos[f"{project.alias}-{branch.name}"] = branch.level

    assert not elevated_staging_repos
