# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.
import re
import warnings
from collections import defaultdict
from urllib.parse import urlparse

import pytest
from taskcluster.utils import scopeMatch

from ciadmin.generate.ciconfig.grants import Grant
from ciadmin.generate.ciconfig.projects import Project
from ciadmin.util.matching import ProjectGrantee

# Known level 3 scopes granted to level 1 contexts that we tolerate for now,
# keyed by role. `check_insecure_grants` warns about these instead of failing,
# and fails if an entry no longer matches anything (strict xfail), so the list
# can't go stale. These are bugs to fix, not supported configurations; remove
# each entry once the underlying grant is gone.
XFAIL_INSECURE_GRANTS = {
    # taskcluster/taskcluster runs collaborator pull requests in its own
    # `taskcluster-level-3` namespace, as it did on community-tc (PR #1062).
    # They should move to level 2 once RFC 0057 (GitHub trust levels) lands.
    "repo:github.com/taskcluster/taskcluster:pull-request": {
        "queue:cancel-task-group:taskcluster-level-3/*",
        "queue:scheduler-id:taskcluster-level-3",
        "queue:seal-task-group:taskcluster-level-3/*",
    },
}


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
        "test-provisioner",
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

            # Scope uses interpolation (see note above) or a parameterized-role
            # placeholder (`<..>`), neither of which references a concrete pool.
            if (
                "{trust_domain}" in target_pool
                or "{level}" in target_pool
                or "<..>" in target_pool
            ):
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
                    if project.get_branch(branch).level == 1:
                        return True

            # Check whether the role corresponds to a pull request.
            if pr.search(role):
                return True

        # Fallback to whether the level-1 regex matches.
        return bool(level_1.search(role))

    insecure_scopes = defaultdict(set)
    xfailed_scopes = defaultdict(set)
    for role in roles:
        if not is_level_1(role.roleId):
            continue

        level_3_scopes = {s for s in role.scopes if level_3.search(s)}
        xfail = XFAIL_INSECURE_GRANTS.get(role.roleId, set())
        xfailed_scopes[role.roleId] = level_3_scopes & xfail
        level_3_scopes -= xfail
        if level_3_scopes:
            insecure_scopes[role.roleId].update(level_3_scopes)

    for roleId, scopes in xfailed_scopes.items():
        if scopes:
            warnings.warn(
                f"XFAIL: {roleId} is granted level 3 scopes {sorted(scopes)} "
                "(known issue, see XFAIL_INSECURE_GRANTS)",
                stacklevel=1,
            )

    # Strict xfail: every listed scope must still be granted, otherwise the
    # entry is stale and must be removed.
    stale_xfails = {
        roleId: sorted(set(scopes) - xfailed_scopes.get(roleId, set()))
        for roleId, scopes in XFAIL_INSECURE_GRANTS.items()
        if set(scopes) - xfailed_scopes.get(roleId, set())
    }
    if stale_xfails:
        print("Stale XFAIL_INSECURE_GRANTS entries (no longer granted; remove them):")
        for roleId, scopes in stale_xfails.items():
            print(f"{roleId}: {scopes}")
    assert not stale_xfails

    if insecure_scopes:
        print("Level 3 scopes are granted to level 1 contexts:")
        for roleId, scopes in insecure_scopes.items():
            print(f"{roleId} is granted the follow scopes that are considered level 3:")
            print(sorted(scopes))
            print()
    assert not insecure_scopes


@pytest.mark.asyncio
async def check_no_pull_request_index_writes(generated):
    """Ensures that pull-request roles can't write to an index namespace that
    isn't confined to pull-requests."""
    roles = generated.filter("Role=.*")
    pr = re.compile(r":pull-request(-untrusted)?$")
    index_write_scope = re.compile(r"^(?:index:insert-task:|queue:route:index\.)(.+)$")
    safe_namespace = re.compile(
        r"(?:^|[.-])(?:pr|head|level-1|garbage|staging)(?:[.-]|$)"
    )

    insecure_scopes = defaultdict(set)
    for role in roles:
        if not pr.search(role.roleId):
            continue

        for scope in role.scopes:
            match = index_write_scope.match(scope)
            if not match:
                continue
            if safe_namespace.search(match.group(1)):
                continue
            insecure_scopes[role.roleId].add(scope)

    if insecure_scopes:
        print(
            "Pull-request roles are granted write access to non pull-request indexes:"
        )
        for roleId, scopes in sorted(insecure_scopes.items()):
            print(f"{roleId} is granted the following index scopes:")
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

    pools = [
        p.workerPoolId
        for p in generated.filter("WorkerPool=.*")
        if not p.workerPoolId.endswith("-alpha")
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
