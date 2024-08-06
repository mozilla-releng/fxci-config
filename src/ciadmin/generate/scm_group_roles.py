# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


from tcadmin.resources import Role
from tcadmin.resources.role import normalizeScopes

from .ciconfig.projects import Project


async def update_resources(resources):
    """
    Manage the `mozilla-group:active_scm_level_L` roles.

    These groups are assigned to everyone who has signed the appropriate paperwork
    to be a committer at level L.  In the current arrangement, they are granted all
    scopes available to all repos at level L or lower.  That is a lot, and there is
    work afoot to change it in bug 1470625.
    """
    resources.manage("Role=mozilla-group:active_scm_level_[123]")

    projects = await Project.fetch_all()

    for level in [1, 2, 3]:
        group = f"active_scm_level_{level}"
        roleId = "mozilla-group:" + group
        description = f"Scopes automatically available to users at SCM level {level}"
        scopes = [f"assume:project:releng:ci-group:{group}"]

        # include an `assume:` scope for each project at level 1
        for project in projects:
            if project.repo_type == "hg":
                for branch in project.branches:
                    if project.get_level(branch.name) == 1:
                        scopes.append(f"assume:{project.role_prefix}:*")

        if scopes:
            resources.add(
                Role(
                    roleId=roleId,
                    description=description,
                    scopes=normalizeScopes(scopes),
                )
            )
