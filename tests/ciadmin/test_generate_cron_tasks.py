# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.appconfig import AppConfig
from tcadmin.resources import Resources
from tcadmin.util import root_url as root_url_mod

from ciadmin.generate import branches, cron_tasks
from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.projects import Project

ROOT_URL = "https://tc-tests.example.com"
GITHUB_TOKEN_SECRET = "project/releng/mobile/github-cron-token"
DEFAULT_OWNER = "default-owner@example.com"
GECKO_OWNER = "gecko-owner@example.com"

HOOK_GROUP_ID = "project-releng"

# The ids `github_project()` generates. Renaming a hook is a delete plus a
# create, so these are spelled out rather than derived.
BASE_HOOK_ID = "cron-task-mozilla-releng-fxci-config"
TARGET_HOOK_ID = f"{BASE_HOOK_ID}/test-build-decision"
BASE_ROLE_ID = f"hook-id:{HOOK_GROUP_ID}/{BASE_HOOK_ID}"
TARGET_ROLE_ID = f"hook-id:{HOOK_GROUP_ID}/{TARGET_HOOK_ID}"

# And the ones `hg_gecko_project()` generates.
HG_BASE_HOOK_ID = "cron-task-mozilla-central"
HG_TARGET_HOOK_ID = f"{HG_BASE_HOOK_ID}/nightly-desktop"

# Mirrors the parts of cron-task-template.yml that consume context values we
# care about. Kept minimal on purpose: this is a test of the context built by
# `make_hooks`, not of the real template's formatting.
SIMPLE_TEMPLATE = {
    "schedulerId": "${trust_domain}-level-${level}",
    "scopes": ["assume:hook-id:${hookGroupId}/${hookId}"],
    "payload": {
        "command": {
            "$flatten": [
                "cron",
                "--repo-url",
                "${project_repo}",
                "--project",
                "${alias}",
                "--level",
                "${level}",
                "--repository-type",
                "${repo_type}",
                {"$if": "branch", "then": ["--branch", "${branch}"]},
                "--trust-domain",
                "${trust_domain}",
                {"$eval": "cron_options"},
            ]
        },
    },
    "metadata": {"name": "Cron task for ${project_repo}"},
}

ENVIRONMENT = Environment(
    name="test",
    root_url=ROOT_URL,
    modify_resources=[],
    worker_manager={},
    cron={
        "default": {"hooks_owner": DEFAULT_OWNER, "notify_emails": []},
        "gecko": {"hooks_owner": GECKO_OWNER, "notify_emails": []},
    },
)


def github_project(**overrides):
    kwargs = {
        "alias": "fxci-config",
        "repo": "https://github.com/mozilla-releng/fxci-config",
        "repo_type": "git",
        "branches": [{"name": "main", "level": 3, "cron": True}],
        "trust_domain": "releng",
        "features": {"taskgraph-cron": True},
        "cron": {"targets": ["test-build-decision"]},
    }
    kwargs.update(overrides)
    return Project(**kwargs)


def hg_gecko_project(**overrides):
    kwargs = {
        "alias": "mozilla-central",
        "repo": "https://hg.mozilla.org/mozilla-central",
        "repo_type": "hg",
        "access": "scm_level_3",
        "branches": [{"name": "default", "cron": True}],
        "trust_domain": "gecko",
        "features": {"taskgraph-cron": True},
        "cron": {"targets": ["nightly-desktop"]},
    }
    kwargs.update(overrides)
    return Project(**kwargs)


@pytest.fixture(autouse=True)
def github_default_branch(monkeypatch):
    """`github_project()`'s repo reports `main` as its default branch."""

    async def fake_default_branch(repo_path):
        return "main"

    monkeypatch.setattr(branches, "get_default_branch", fake_default_branch)


@pytest.fixture(autouse=True)
def appconfig(monkeypatch):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", ROOT_URL)
    # tcadmin memoizes the root url in a module-level global. Reset it so the
    # env var above is honoured, and so this module doesn't leak a cached value
    # into the rest of the suite.
    monkeypatch.setattr(root_url_mod, "_root_url", None)
    with AppConfig._as_current(AppConfig()):
        yield


@pytest.fixture
def cron_template(mock_ciconfig_file):
    mock_ciconfig_file("cron-task-template.yml", SIMPLE_TEMPLATE)


def by_id(resources):
    """Split generated resources into {hookId: Hook} and {roleId: Role}."""
    hooks = {r.hookId: r for r in resources if hasattr(r, "hookId")}
    roles = {r.roleId: r for r in resources if hasattr(r, "roleId")}
    return hooks, roles


def command_of(hook):
    return hook.task["payload"]["command"]


def value_of(hook, option):
    """Return the value of a command-line option in a hook's task payload."""
    command = command_of(hook)
    return command[command.index(option) + 1]


@pytest.mark.asyncio
async def test_github_project(cron_template):
    """Hooks and roles for a github project with one branch and one target"""
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, roles = by_id(resources)

    # One base hook plus one per target, and a role named after each hook.
    assert set(hooks) == {BASE_HOOK_ID, TARGET_HOOK_ID}
    assert set(roles) == {BASE_ROLE_ID, TARGET_ROLE_ID}

    base = hooks[BASE_HOOK_ID]
    target = hooks[TARGET_HOOK_ID]

    assert base.hookGroupId == HOOK_GROUP_ID
    assert base.name == f"{HOOK_GROUP_ID}/{BASE_HOOK_ID}"
    assert target.hookGroupId == HOOK_GROUP_ID
    assert target.name == f"{HOOK_GROUP_ID}/{TARGET_HOOK_ID}"

    # Only the base hook is scheduled. The target has no trigger and takes
    # no input.
    assert base.schedule == ("0 0,15,30,45 * * * *",)
    assert target.schedule == ()
    assert target.bindings == ()
    assert target.triggerSchema["additionalProperties"] is False

    # Both hooks carry the same context
    for hook in (base, target):
        assert value_of(hook, "--branch") == "main"
        assert value_of(hook, "--level") == "3"
        assert hook.task["schedulerId"] == "releng-level-3"
        assert value_of(hook, "--github-token-secret") == GITHUB_TOKEN_SECRET

    # Only the target hook forces a specific cron job to run.
    assert not any(a.startswith("--force-run") for a in command_of(base))
    assert "--force-run=test-build-decision" in command_of(target)

    # The base role may run any cron target.
    # Each target role runs only its own.
    role_prefix = "assume:repo:github.com/mozilla-releng/fxci-config"
    assert f"{role_prefix}:cron:*" in roles[BASE_ROLE_ID].scopes
    assert f"{role_prefix}:cron:test-build-decision" in roles[TARGET_ROLE_ID].scopes
    assert f"{role_prefix}:cron:*" not in roles[TARGET_ROLE_ID].scopes

    # Only the target role attaches the secret scope directly.
    assert f"secrets:get:{GITHUB_TOKEN_SECRET}" not in roles[BASE_ROLE_ID].scopes
    assert f"secrets:get:{GITHUB_TOKEN_SECRET}" in roles[TARGET_ROLE_ID].scopes

    assert base.owner == DEFAULT_OWNER


@pytest.mark.asyncio
async def test_hg_gecko_project(cron_template):
    resources = await cron_tasks.make_hooks(hg_gecko_project(), ENVIRONMENT)
    hooks, roles = by_id(resources)

    assert set(hooks) == {HG_BASE_HOOK_ID, HG_TARGET_HOOK_ID}

    for hook in hooks.values():
        assert value_of(hook, "--branch") == "default"
        assert value_of(hook, "--level") == "3"
        assert "--github-token-secret" not in command_of(hook)

    for role in roles.values():
        assert not any(s.startswith("secrets:get:") for s in role.scopes)

    assert hooks[HG_BASE_HOOK_ID].owner == GECKO_OWNER


@pytest.mark.asyncio
async def test_one_hook_and_role_per_target(cron_template):
    project = github_project(cron={"targets": ["alpha", "beta", "gamma"]})
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, roles = by_id(resources)

    assert set(hooks) == {
        BASE_HOOK_ID,
        f"{BASE_HOOK_ID}/alpha",
        f"{BASE_HOOK_ID}/beta",
        f"{BASE_HOOK_ID}/gamma",
    }
    assert set(roles) == {f"hook-id:{HOOK_GROUP_ID}/{hook_id}" for hook_id in hooks}


@pytest.mark.asyncio
async def test_target_with_pulse_bindings(cron_template):
    """A bound target forwards its bindings and accepts input by default."""
    project = github_project(
        cron={
            "targets": [
                {
                    "target": "on-push",
                    "bindings": [
                        {
                            "exchange": "exchange/taskcluster-github/v1/push",
                            "routing_key_pattern": "primary.mozilla-releng.fxci-config",
                        }
                    ],
                }
            ]
        }
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = by_id(resources)

    target = hooks[f"{BASE_HOOK_ID}/on-push"]
    (binding,) = target.bindings
    assert binding.exchange == "exchange/taskcluster-github/v1/push"
    assert binding.routingKeyPattern == "primary.mozilla-releng.fxci-config"
    assert target.triggerSchema["additionalProperties"] is True


@pytest.mark.asyncio
async def test_allow_input_can_be_set_without_bindings(cron_template):
    project = github_project(
        cron={"targets": [{"target": "canary", "allow-input": True}]}
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = by_id(resources)

    target = hooks[f"{BASE_HOOK_ID}/canary"]
    assert target.triggerSchema["additionalProperties"] is True


@pytest.mark.asyncio
async def test_project_can_override_hooks_owner(cron_template):
    project = github_project(
        cron={"targets": ["test-build-decision"], "hooks_owner": "me@example.com"}
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = by_id(resources)

    assert hooks[BASE_HOOK_ID].owner == "me@example.com"
    assert hooks[TARGET_HOOK_ID].owner == "me@example.com"


@pytest.mark.asyncio
async def test_string_target_is_equivalent_to_dict_target(cron_template):
    """`targets: [nightly]` and its expanded form must generate the same thing.

    Almost every project in projects.yml uses the bare string form, and
    `_convert_cron_targets` is where a richer target schema would be added.
    """
    from_string = await cron_tasks.make_hooks(
        github_project(cron={"targets": ["nightly"]}), ENVIRONMENT
    )
    from_dict = await cron_tasks.make_hooks(
        github_project(cron={"targets": [{"target": "nightly", "bindings": []}]}),
        ENVIRONMENT,
    )

    assert from_string == from_dict


# ---------------------------------------------------------------------------
# Cron on more than one branch (bug 2030902).
# ---------------------------------------------------------------------------


def test_cron_branches_are_required():
    with pytest.raises(ValueError, match="must mark at least one branch"):
        github_project(branches=[{"name": "main", "level": 3, "cron": False}])


@pytest.mark.asyncio
async def test_default_branch_comes_from_github(cron_template, monkeypatch):
    """The unsuffixed hookId follows GitHub, not projects.yml."""

    async def default_is_trunk(repo_path):
        return "trunk"

    monkeypatch.setattr(branches, "get_default_branch", default_is_trunk)

    project = github_project(
        # projects.yml disagrees with github on purpose here
        default_branch="main",
        branches=[
            {"name": "trunk", "level": 3, "cron": True},
            {"name": "main", "level": 3, "cron": True},
        ],
    )
    hooks, _ = by_id(await cron_tasks.make_hooks(project, ENVIRONMENT))

    # `trunk` is the default now, so it keeps the plain id and `main` is
    # the one that gets suffixed.
    assert value_of(hooks[BASE_HOOK_ID], "--branch") == "trunk"
    assert value_of(hooks[f"{BASE_HOOK_ID}-main"], "--branch") == "main"


@pytest.mark.asyncio
async def test_each_branch_gets_its_own_hooks(cron_template):
    project = github_project(
        branches=[
            {"name": "main", "level": 3, "cron": True},
            {"name": "beta", "level": 3, "cron": True},
        ],
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, roles = by_id(resources)

    # The default branch keeps the ids it already had; the extra branch adds
    # its own. Nothing an existing project generates today changes.
    assert set(hooks) == {
        BASE_HOOK_ID,
        TARGET_HOOK_ID,
        f"{BASE_HOOK_ID}-beta",
        f"{BASE_HOOK_ID}-beta/test-build-decision",
    }
    assert set(roles) == {f"hook-id:{HOOK_GROUP_ID}/{hook_id}" for hook_id in hooks}

    assert value_of(hooks[BASE_HOOK_ID], "--branch") == "main"
    assert value_of(hooks[f"{BASE_HOOK_ID}-beta"], "--branch") == "beta"


@pytest.mark.asyncio
async def test_each_branch_gets_its_own_level(cron_template):
    """
    A cron task runs at the level of the branch it runs on.

    Only branches at or above the default branch's level may run cron; see
    `test_cron_branches_may_not_be_below_the_default_branch` below.
    """
    project = github_project(
        branches=[
            {"name": "main", "level": 1, "cron": True},
            {"name": "production", "level": 3, "cron": True},
        ],
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = by_id(resources)

    for hook_id, level in ((BASE_HOOK_ID, "1"), (f"{BASE_HOOK_ID}-production", "3")):
        assert value_of(hooks[hook_id], "--level") == level
        assert hooks[hook_id].task["schedulerId"] == f"releng-level-{level}"


@pytest.mark.asyncio
async def test_cron_branch_hooks_share_role(cron_template):
    """
    Cron hooks are per-branch, but the scopes they grant are not: each branch's
    role points at the same repo-wide `cron:*` role, whose scopes are generated
    at the project's `default_branch.level`.
    """
    project = github_project(
        branches=[
            {"name": "main", "level": 1, "cron": True},
            {"name": "production", "level": 3, "cron": True},
        ],
    )
    _, roles = by_id(await cron_tasks.make_hooks(project, ENVIRONMENT))

    scope = f"assume:{project.role_prefix}:cron:*"
    assert scope in roles[BASE_ROLE_ID].scopes
    assert scope in roles[f"{BASE_ROLE_ID}-production"].scopes


def test_cron_branches_may_not_be_below_the_default_branch(cron_template):
    with pytest.raises(ValueError):
        github_project(
            branches=[
                {"name": "main", "level": 3, "cron": True},
                {"name": "dev", "level": 1, "cron": True},
            ],
        )


def test_cron_branches_may_not_be_globs():
    with pytest.raises(ValueError, match="cannot be globs"):
        github_project(
            branches=[
                {"name": "main", "level": 3, "cron": True},
                {"name": "releases/*", "level": 3, "cron": True},
            ]
        )


def test_unknown_cron_target_keys_are_rejected():
    with pytest.raises(ValueError, match="cron: true"):
        github_project(cron={"targets": [{"target": "nightly", "branch": "beta"}]})


@pytest.mark.asyncio
async def test_update_resources_skips_projects_without_the_feature(
    cron_template, mock_ciconfig_file, set_environment
):
    mock_ciconfig_file(
        "environments.yml",
        {
            "test": {
                "root_url": ROOT_URL,
                "modify_resources": [],
                "worker_manager": {},
                "cron": {
                    "default": {"hooks_owner": DEFAULT_OWNER, "notify_emails": []},
                },
            }
        },
    )
    mock_ciconfig_file(
        "projects.yml",
        {
            "with-cron": {
                "repo": "https://github.com/mozilla/with-cron",
                "repo_type": "git",
                "trust_domain": "foo",
                "branches": [{"name": "main", "level": 3, "cron": True}],
                "features": {"taskgraph-cron": True},
                "cron": {"targets": ["nightly"]},
            },
            "without-cron": {
                "repo": "https://github.com/mozilla/without-cron",
                "repo_type": "git",
                "trust_domain": "foo",
                "branches": [{"name": "main", "level": 3}],
                "features": {},
            },
        },
    )

    resources = Resources()
    resources.manage("Hook=project-releng/cron-task-.*")
    resources.manage("Role=hook-id:project-releng/cron-task-.*")
    with set_environment("test"):
        await cron_tasks.update_resources(resources)

    hooks, _ = by_id(resources)
    assert "cron-task-mozilla-with-cron" in hooks
    assert "cron-task-mozilla-without-cron" not in hooks
