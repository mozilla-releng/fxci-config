# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.
import re
from collections import defaultdict
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
async def check_grant_pools(generate_resources):
    """
    Ensures that we don't grant things for non-existent worker pools.
    """
    generated = await generate_resources("worker_pools")

    # Known scopes that reference worker-pools.
    prefixes = (
        "generic-worker:allow-rdp:",
        "generic-worker:os-group:",
        "generic-worker:run-as-administrator:",
        "queue:create-task:",
        "queue:quarantine-worker:",
    )
    # These providers are not managed by worker-manager, so valid pools can't
    # be detected.
    ignore_providers = {
        "bitbar",
        "built-in",
        "lambda",
        "performance-hardware",
        "proj-autophone",
        "releng-hardware",
        "scriptworker-k8s",
        "scriptworker-prov-v1",
    }

    # We validate the raw grants rather than the generated grants to allow for
    # things like `{trust_domain}-t/*`. This will inevitably generate scopes
    # that don't reference valid pools, but that's ok as the intent of this
    # check is to keep grants.d yml files clean, not the generated grants.
    grants = await Grant.fetch_all()
    pools = [p.workerPoolId for p in generated.filter("WorkerPool=.*")]
    invalid_scopes = set()

    for grant in grants:
        for scope in grant.scopes:
            assert isinstance(scope, str)

            if not scope.startswith(prefixes):
                continue

            target_pool = scope.rsplit(":", 1)[-1]

            # These scopes can have slashes *after* the worker-pool.
            if "os-group" in scope or "quarantine-worker" in scope:
                parts = target_pool.split("/")[:2]
                target_pool = "/".join(parts)

            # Scope uses interpolation (see note above).
            if "{trust_domain}" in target_pool or "{level}" in target_pool:
                continue

            # Scope uses a wildcard which encompasses providers outside of
            # worker-manager's control.
            if "/" not in target_pool:
                continue

            # Scope uses a provider not managed by worker-manager.
            provider = target_pool.split("/")[0]
            if provider in ignore_providers:
                continue

            if target_pool.endswith("*"):
                target_pool = target_pool[:-1]

                matches = {p for p in pools if p.startswith(target_pool)}
                if not matches:
                    invalid_scopes.add(scope)
            else:
                if target_pool not in pools:
                    invalid_scopes.add(scope)

    if invalid_scopes:
        print(
            "Grants are given for the following undefined worker-pools:\n"
            + "\n".join(sorted(invalid_scopes))
        )
    assert not invalid_scopes


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

                if ":branch:" in role:
                    branch = role.split(":")[-1]
                    if project.get_level(branch) == 1:
                        return True

            # Check whether the role corresponds to a pull request.
            if pr.search(role):
                return True

        # Fallback to whether the level-1 regex matches.
        return bool(level_1.search(role))

    insecure_scopes = defaultdict(set)
    for role in roles:
        if not is_level_1(role.roleId):
            continue

        level_3_scopes = {s for s in role.scopes if level_3.search(s)}
        if level_3_scopes:
            insecure_scopes[role.roleId].update(level_3_scopes)

    if insecure_scopes:
        print("Level 3 scopes are granted to level 1 contexts:")
        for roleId, scopes in insecure_scopes.items():
            print(f"{roleId} is granted the follow scopes that are considered level 3:")
            print(sorted(scopes))
            print()
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

    # FIXME ignore ci-* pools until fxci-config is actually switched to using releng-*
    pools = [
        p.workerPoolId
        for p in generated.filter("WorkerPool=.*")
        if not p.workerPoolId.startswith("ci-")
    ]
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
