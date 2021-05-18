# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.util.scopes import satisfies

from ciadmin.generate.ciconfig.projects import Project

PRIORITIES = (
    "highest",
    "very-high",
    "high",
    "medium",
    "low",
    "very-low",
    "lowest",
    "normal",
)


async def project_scopes(resolver, level):
    projects = await Project.fetch_all()
    scopes = ["assume:mozilla-group:active_scm_level_{}".format(level)]
    for project in projects:
        if project.level == level:
            scopes.append("assume:{}:*".format(project.role_prefix))
    return resolver.expandScopes(scopes)


@pytest.fixture(scope="module")
async def l1_scopes(generated_resolver):
    return await project_scopes(generated_resolver, level=1)


@pytest.fixture(scope="module")
async def l3_scopes(generated_resolver):
    return await project_scopes(generated_resolver, level=3)


@pytest.mark.parametrize(
    "scope,present",
    [
        # try (level 1) gets dep-signing, but nothing else
        ("project:comm:thunderbird:releng:signing:cert:dep-signing", True),
        ("project:comm:thunderbird:releng:signing:cert:nightly-signing", False),
        ("project:comm:thunderbird:releng:signing:cert:release-signing", False),
        ("project:releng:signing:cert:dep-signing", True),
        ("project:releng:signing:cert:nightly-signing", False),
        ("project:releng:signing:cert:release-signing", False),
        ("queue:create-task:low:scriptworker-k8s/gecko-t-*", True),
        ("queue:create-task:low:scriptworker-k8s/comm-t-*", True),
        ("queue:create-task:low:scriptworker-k8s/gecko-1-*", True),
        ("queue:create-task:low:scriptworker-k8s/comm-1-*", True),
    ]
    # Negative worker scopes are parameterized to ensure that no priority is granted
    + [
        ("queue:create-task:{priority}:scriptworker-prov-v1/signing-mac-v1", False)
        for priority in PRIORITIES
    ]
    + [
        ("queue:create-task:{priority}:scriptworker-prov-v1/tb-signing-mac-v1", False)
        for priority in PRIORITIES
    ]
    + [
        (f"queue:create-task:{priority}:scriptworker-k8s/{trust_domain}-3-*", False)
        for priority in PRIORITIES
        for trust_domain in ("gecko", "comm")
    ],
)
def check_l1_scopes(l1_scopes, scope, present):
    if present:
        assert satisfies(l1_scopes, [scope])
    else:
        assert not satisfies(l1_scopes, [scope])


@pytest.mark.parametrize(
    "scope,present",
    [
        # level 3 gets all kinds of signing
        ("project:comm:thunderbird:releng:signing:cert:dep-signing", True),
        ("project:comm:thunderbird:releng:signing:cert:nightly-signing", True),
        ("project:comm:thunderbird:releng:signing:cert:release-signing", True),
        ("project:releng:signing:cert:dep-signing", True),
        ("project:releng:signing:cert:nightly-signing", True),
        ("project:releng:signing:cert:release-signing", True),
        ("queue:create-task:highest:scriptworker-prov-v1/signing-mac-v1", True),
        ("queue:create-task:highest:scriptworker-prov-v1/tb-signing-mac-v1", True),
        ("queue:create-task:highest:scriptworker-k8s/gecko-3-*", True),
        ("queue:create-task:highest:scriptworker-k8s/comm-3-*", True),
    ],
)
def check_l3_scopes(l3_scopes, scope, present):
    if present:
        assert satisfies(l3_scopes, [scope])
    else:
        assert not satisfies(l3_scopes, [scope])
