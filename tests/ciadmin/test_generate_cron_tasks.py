# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.appconfig import AppConfig
from tcadmin.resources import Resources
from tcadmin.util import root_url as root_url_mod

from ciadmin.generate import cron_tasks
from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.projects import Project

ROOT_URL = "https://tc-tests.example.com"
GITHUB_TOKEN_SECRET = "project/releng/mobile/github-cron-token"
DEFAULT_OWNER = "default-owner@example.com"
GECKO_OWNER = "gecko-owner@example.com"

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
        "branches": [{"name": "main", "level": 3}],
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
        "branches": [{"name": "default"}],
        "trust_domain": "gecko",
        "features": {"taskgraph-cron": True},
        "cron": {"targets": ["nightly-desktop"]},
    }
    kwargs.update(overrides)
    return Project(**kwargs)


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


def hooks_and_roles(resources):
    hooks = [r for r in resources if hasattr(r, "hookId")]
    roles = [r for r in resources if hasattr(r, "roleId")]
    return hooks, roles


def command_of(hook):
    return hook.task["payload"]["command"]


# ---------------------------------------------------------------------------
# Identity: hookId and roleId are resource identities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_hook_identity(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    base = hooks[0]
    assert base.hookGroupId == "project-releng"
    assert base.hookId == "cron-task-mozilla-releng-fxci-config"
    assert base.name == "project-releng/cron-task-mozilla-releng-fxci-config"


@pytest.mark.asyncio
async def test_target_hook_identity(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    target = hooks[1]
    assert target.hookGroupId == "project-releng"
    assert target.hookId == "cron-task-mozilla-releng-fxci-config/test-build-decision"


@pytest.mark.asyncio
async def test_role_ids_track_hook_ids(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, roles = hooks_and_roles(resources)

    # Every hook has exactly one role, named after it. A hook whose role goes
    # missing runs with no scopes at all.
    assert {r.roleId for r in roles} == {
        f"hook-id:{h.hookGroupId}/{h.hookId}" for h in hooks
    }


@pytest.mark.asyncio
async def test_one_hook_and_role_per_target_plus_base(cron_template):
    project = github_project(cron={"targets": ["alpha", "beta", "gamma"]})
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, roles = hooks_and_roles(resources)

    assert len(hooks) == 4  # one base + one per target
    assert len(roles) == 4


# ---------------------------------------------------------------------------
# Triggers: only the base hook is scheduled.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_hook_runs_every_fifteen_minutes(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    # tcadmin normalizes schedule to a tuple.
    assert hooks[0].schedule == ("0 0,15,30,45 * * * *",)


@pytest.mark.asyncio
async def test_target_hooks_are_not_scheduled(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    # Target hooks are fired by hand or by a pulse binding, never by the clock.
    assert hooks[1].schedule == ()


@pytest.mark.asyncio
async def test_pulse_bindings_are_forwarded(cron_template):
    project = github_project(
        cron={
            "targets": [
                {
                    "target": "on-push",
                    "bindings": [
                        {
                            "exchange": "exchange/taskcluster-github/v1/push",
                            "routing_key_pattern": "primary.mozilla.example",
                        }
                    ],
                }
            ]
        }
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    binding = hooks[1].bindings[0]
    assert binding.exchange == "exchange/taskcluster-github/v1/push"
    assert binding.routingKeyPattern == "primary.mozilla.example"


@pytest.mark.asyncio
async def test_allow_input_defaults_to_false_without_bindings(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    assert hooks[1].triggerSchema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_allow_input_defaults_to_true_with_bindings(cron_template):
    project = github_project(
        cron={
            "targets": [
                {
                    "target": "on-push",
                    "bindings": [
                        {
                            "exchange": "exchange/taskcluster-github/v1/push",
                            "routing_key_pattern": "primary.mozilla.example",
                        }
                    ],
                }
            ]
        }
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    assert hooks[1].triggerSchema["additionalProperties"] is True


@pytest.mark.asyncio
async def test_allow_input_can_be_set_explicitly(cron_template):
    project = github_project(
        cron={"targets": [{"target": "canary", "allow-input": True}]}
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    assert hooks[1].triggerSchema["additionalProperties"] is True


# ---------------------------------------------------------------------------
# Task content: the branch and level handed to build-decision.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_passed_to_build_decision(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    for hook in hooks:
        command = command_of(hook)
        assert "--branch" in command
        assert command[command.index("--branch") + 1] == "main"


@pytest.mark.asyncio
async def test_level_comes_from_the_default_branch(cron_template):
    # The project's only branch is `main` at level 3, so every generated task
    # carries level 3 -- in the argument *and* in the schedulerId.
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    for hook in hooks:
        command = command_of(hook)
        assert command[command.index("--level") + 1] == "3"
        assert hook.task["schedulerId"] == "releng-level-3"


@pytest.mark.asyncio
async def test_force_run_only_on_target_hooks(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    assert not any(a.startswith("--force-run") for a in command_of(hooks[0]))
    assert "--force-run=test-build-decision" in command_of(hooks[1])


@pytest.mark.asyncio
async def test_github_projects_get_a_token_secret(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, roles = hooks_and_roles(resources)

    for hook in hooks:
        command = command_of(hook)
        assert command[command.index("--github-token-secret") + 1] == (
            GITHUB_TOKEN_SECRET
        )

    # Only the target role attaches this scope directly.
    base_role, target_role = roles
    assert f"secrets:get:{GITHUB_TOKEN_SECRET}" not in base_role.scopes
    assert f"secrets:get:{GITHUB_TOKEN_SECRET}" in target_role.scopes


@pytest.mark.asyncio
async def test_hg_projects_get_no_token_secret(cron_template):
    resources = await cron_tasks.make_hooks(hg_gecko_project(), ENVIRONMENT)
    hooks, roles = hooks_and_roles(resources)

    for hook in hooks:
        assert "--github-token-secret" not in command_of(hook)
    for role in roles:
        assert not any(s.startswith("secrets:get:") for s in role.scopes)


# ---------------------------------------------------------------------------
# Scopes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_role_holds_scopes_for_every_target(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    _, roles = hooks_and_roles(resources)

    assert "assume:repo:github.com/mozilla-releng/fxci-config:cron:*" in (
        roles[0].scopes
    )


@pytest.mark.asyncio
async def test_target_role_is_scoped_to_its_target_only(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    _, roles = hooks_and_roles(resources)

    scopes = roles[1].scopes
    assert (
        "assume:repo:github.com/mozilla-releng/fxci-config:cron:test-build-decision"
        in scopes
    )
    assert "assume:repo:github.com/mozilla-releng/fxci-config:cron:*" not in scopes


# ---------------------------------------------------------------------------
# Per-environment cron config.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gecko_projects_use_the_gecko_cron_config(cron_template):
    resources = await cron_tasks.make_hooks(hg_gecko_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    assert hooks[0].owner == GECKO_OWNER


@pytest.mark.asyncio
async def test_other_projects_use_the_default_cron_config(cron_template):
    resources = await cron_tasks.make_hooks(github_project(), ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    assert hooks[0].owner == DEFAULT_OWNER


@pytest.mark.asyncio
async def test_project_can_override_hooks_owner(cron_template):
    project = github_project(
        cron={"targets": ["test-build-decision"], "hooks_owner": "me@example.com"}
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    assert hooks[0].owner == "me@example.com"


# ---------------------------------------------------------------------------
# Target shorthand.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_string_target_is_equivalent_to_dict_target(cron_template):
    from_string = await cron_tasks.make_hooks(
        github_project(cron={"targets": ["nightly"]}), ENVIRONMENT
    )
    from_dict = await cron_tasks.make_hooks(
        github_project(cron={"targets": [{"target": "nightly", "bindings": []}]}),
        ENVIRONMENT,
    )

    assert [r.to_json() for r in from_string] == [r.to_json() for r in from_dict]


# ---------------------------------------------------------------------------
# The multi-branch gap this module's refactor has to close (bug 2030902).
#
# `cron_tasks.py` already reads a per-target `branch` key, but the hookId is
# derived from the repo path alone -- so two branches of the same target
# collapse onto one resource. The test below pins that behaviour deliberately.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_target_branch_overrides_the_default(cron_template):
    project = github_project(
        branches=[{"name": "main", "level": 3}, {"name": "beta", "level": 3}],
        cron={"targets": [{"target": "nightly", "branch": "beta"}]},
    )
    resources = await cron_tasks.make_hooks(project, ENVIRONMENT)
    hooks, _ = hooks_and_roles(resources)

    base, target = hooks
    assert command_of(base)[command_of(base).index("--branch") + 1] == "main"
    assert command_of(target)[command_of(target).index("--branch") + 1] == "beta"


@pytest.mark.asyncio
async def test_branch_does_not_appear_in_the_hook_id(cron_template):
    """Two branches of one target currently produce one hookId.

    This is the collision bug 2030902 has to resolve. When it does, this test
    should be replaced by one asserting the branch *is* part of the identity --
    and every other identity test in this module must still pass unchanged, so
    that single-branch projects keep the hookIds they have today.
    """
    on_main = await cron_tasks.make_hooks(
        github_project(cron={"targets": [{"target": "nightly", "branch": "main"}]}),
        ENVIRONMENT,
    )
    on_beta = await cron_tasks.make_hooks(
        github_project(
            branches=[{"name": "main", "level": 3}, {"name": "beta", "level": 3}],
            cron={"targets": [{"target": "nightly", "branch": "beta"}]},
        ),
        ENVIRONMENT,
    )

    main_hooks, _ = hooks_and_roles(on_main)
    beta_hooks, _ = hooks_and_roles(on_beta)

    assert [h.hookId for h in main_hooks] == [h.hookId for h in beta_hooks]


# ---------------------------------------------------------------------------
# update_resources: which projects get hooks at all.
# ---------------------------------------------------------------------------


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
                "branches": [{"name": "main", "level": 3}],
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

    hook_ids = {r.hookId for r in resources if hasattr(r, "hookId")}
    assert "cron-task-mozilla-with-cron" in hook_ids
    assert "cron-task-mozilla-without-cron" not in hook_ids
