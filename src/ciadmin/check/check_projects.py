# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

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
