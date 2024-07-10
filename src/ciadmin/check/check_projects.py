# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.
import re

import pytest

from ciadmin.generate.ciconfig.projects import Project


@pytest.mark.asyncio
async def check_repo_url():
    """
    Ensures that the project repo doesn't end with a `'`
    """

    projects = await Project.fetch_all()
    errors = []

    for project in projects:
        if project.repo.endswith("/"):
            errors.append(f"{project.repo} ends with a '/'!")
    assert not errors


@pytest.mark.asyncio
async def check_trust_domains():
    """
    Ensures that trust domains are valid.
    """
    projects = await Project.fetch_all()
    trust_domains = set(project.trust_domain for project in projects)
    errors = []

    for trust_domain in trust_domains:
        if not trust_domain:
            continue

        # Ensure no regex special characters, but '-' is ok.
        td = trust_domain.replace("-", "_")
        if td != re.escape(td):
            errors.append(f"{trust_domain} contains regex special characters!")

    assert not errors


@pytest.mark.asyncio
async def check_wildcard_projects():
    """
    Ensures that all projects containing a * only use level 1 and the mozilla
    trust domain.
    """
    projects = [p for p in await Project.fetch_all() if p.repo.endswith("*")]
    allowed_trust_domains = ("mozilla",)
    errors = []

    for p in projects:
        if p.trust_domain not in allowed_trust_domains:
            errors.append(
                f"{p.alias} uses wildcard repo ({p.repo}) "
                f"with disallowed trust domain ({p.trust_domain})!"
            )

        for b in p.branches:
            if b.level != 1:
                errors.append(
                    f"{p.alias}'s {b.name} branch uses wildcard repo"
                    f"({p.repo}) with level {b.level}!"
                )

    if errors:
        print("\n".join(errors))
    assert not errors
