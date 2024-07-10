# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.
import re
from urllib.parse import urlparse

import pytest
from taskcluster.utils import scopeMatch

from ciadmin.generate.ciconfig.grants import Grant
from ciadmin.generate.ciconfig.projects import Project
from ciadmin.util.matching import ProjectGrantee


@pytest.mark.asyncio
async def check_grant_aliases():
    """
    Ensures that we don't grant things to non-existent projects.
    """
    grants = await Grant.fetch_all()
    aliases = {p.alias for p in await Project.fetch_all()}
    unknown_aliases = set()

    for grant in grants:
        for grantee in grant.grantees:
            if not isinstance(grantee, ProjectGrantee):
                continue
            if not grantee.alias:
                continue

            if isinstance(grantee.alias, str):
                grantee_aliases = {grantee.alias}
            else:
                grantee_aliases = set(grantee.alias)

            unknown_aliases.update(grantee_aliases - aliases)

    if unknown_aliases:
        print(
            "Grants are given to the following undefined projects:\n"
            + "\n".join(sorted(unknown_aliases))
        )
    assert not unknown_aliases


@pytest.mark.asyncio
async def check_insecure_grants(generate_resources):
    """
    Ensures we don't grant any level 3 scopes to level 1 contexts.
    """
    roles = (await generate_resources()).filter("Role=.*")
    projects = await Project.fetch_all()

    level_prefixes = {"level", "in-tree-action"}
    level_prefixes.update({p.trust_domain for p in projects})
    level_1 = re.compile(f"({'|'.join(level_prefixes)})[-_]1")
    level_3 = re.compile(f"({'|'.join(level_prefixes)})[-_]3")
    pr = re.compile(r":pull-request(-untrusted)?$")

    def is_level_1(role):
        if role.startswith("repo:"):
            # Check whether the associated project is level 1.
            repo_url = role.split(":")[1]
            for project in projects:
                result = urlparse(project.repo)
                if repo_url != result.netloc + result.path:
                    continue

                if project.access == "scm_level_1":
                    return True

                # Technically this doesn't make the whole repo level 1
                # A better test here would be to examine the role more
                # thoroughly to see if the role corresponds to an L1
                # branch or something else. This will become relevant
                # if/when we have projects that contain branches across
                # more than one level.
                for branch in project.branches:
                    if branch.level == 1:
                        return True

            # Check whether the role corresponds to a pull request.
            if pr.search(role):
                return True

        # Fallback to whether the level-1 regex matches.
        return bool(level_1.search(role))

    insecure_scopes = set()
    for role in roles:
        if not is_level_1(role.roleId):
            continue

        level_3_scopes = {s for s in role.scopes if level_3.search(s)}
        if level_3_scopes:
            insecure_scopes.update(level_3_scopes)

    if insecure_scopes:
        print(
            "Level 3 scopes are granted to level 1 contexts:\n  "
            + "\n  ".join(sorted(insecure_scopes))
        )
    assert not insecure_scopes


@pytest.mark.asyncio
async def check_inaccessible_pools(generated):
    """
    Checks for pools that no roles (other than root) are able to create tasks in.
    """
    roles = generated.filter("Role=.*")
    # Ignore 'root' level roles.
    ignore_roles = {
        "mozilla-group:fxci_tc_admins",
        "mozilla-group:releng",
        "mozilla-group:team_relops",
        "mozilla-group:team_taskcluster",
    }
    roles = [role for role in roles if all(i not in role.roleId for i in ignore_roles)]

    pools = [p.workerPoolId for p in generated.filter("WorkerPool=.*")]
    remaining_pools = set(pools)

    priorities = {
        "highest",
        "very-high",
        "high",
        "medium",
        "low",
        "very-low",
        "lowest",
        "normal",
    }
    for pool in pools:
        required_scopes = []
        for priority in priorities:
            required_scopes.append([f"queue:create-task:{priority}:{pool}"])

        for role in roles:
            if scopeMatch(role.scopes, required_scopes):
                remaining_pools.remove(pool)
                break

    if remaining_pools:
        print(
            "No roles have scopes to use the following pools:\n  "
            + "\n  ".join(sorted(remaining_pools))
        )
    assert not remaining_pools
