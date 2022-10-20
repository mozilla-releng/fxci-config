# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from ciadmin.generate.ciconfig.grants import Grant, ProjectGrantee
from ciadmin.generate.ciconfig.projects import Project


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
