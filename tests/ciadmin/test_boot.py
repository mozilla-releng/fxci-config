import subprocess

import pytest
from tcadmin.resources import Resources
from tcadmin.resources.role import Role

from ciadmin.boot import filter_resources_by_modules
from ciadmin.generate import hg_pushes, scm_group_roles


def run_ci_admin(*args):
    return subprocess.run(["ci-admin", *args], capture_output=True, text=True)


def test_generated_accepted_with_partial_resources():
    """--generated + --resources no longer hits the old blanket rejection.

    The generated file doesn't exist, so this still fails -- but with a
    file-loading error rather than the removed "cannot be combined" check,
    proving the combination is no longer rejected outright.
    """
    result = run_ci_admin(
        "diff",
        "--environment",
        "firefoxci",
        "--generated",
        "/tmp/does-not-exist.json",
        "--resources",
        "worker_pools",
    )
    assert result.returncode != 0
    assert "--generated cannot be combined with --resources" not in result.stderr


def _role(role_id):
    return Role.from_api({"roleId": role_id, "description": "d", "scopes": []})


@pytest.mark.asyncio
async def test_filter_resources_by_modules_filters_resource_list():
    "Only resources matching the selected modules' patterns are kept."
    hg_push_role = _role("hook-id:hg-push/foo")
    scm_role = _role("mozilla-group:active_scm_level_1")
    resources = Resources(
        resources=[hg_push_role, scm_role],
        managed=[*hg_pushes.MANAGED_PATTERNS, *scm_group_roles.MANAGED_PATTERNS],
    )

    narrowed = await filter_resources_by_modules(resources, [hg_pushes])

    assert list(narrowed.resources) == [hg_push_role]


@pytest.mark.asyncio
async def test_filter_resources_by_modules_shrinks_managed_scope():
    """The managed scope shrinks along with the resource list.

    This is the property that matters for security: a caller that fetches
    "current" state scoped to `narrowed.managed` should no longer need
    scopes for excluded resource types.
    """
    resources = Resources(
        resources=[],
        managed=[*hg_pushes.MANAGED_PATTERNS, *scm_group_roles.MANAGED_PATTERNS],
    )

    narrowed = await filter_resources_by_modules(resources, [hg_pushes])

    assert narrowed.is_managed("Role=hook-id:hg-push/foo")
    assert not narrowed.is_managed("Role=mozilla-group:active_scm_level_1")
