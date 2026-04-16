# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from tcadmin.resources import Resources

from ciadmin.generate.ciconfig.hooks import Hook
from ciadmin.generate.hooks import generate_hook_variants, update_resources


def make_hook(**kwargs):
    defaults = dict(
        hook_group_id="project-foo",
        hook_id="my-hook",
        name="My Hook",
        description="A test hook",
        owner="test@example.com",
        email_on_error=False,
        scopes=["queue:create-task:lowest:my-pool"],
        template_file="hook-templates/project-foo/my-hook.yml",
    )
    defaults.update(kwargs)
    return Hook(**defaults)


def test_substitution():
    hook = make_hook(
        hook_group_id="project-{group}",
        hook_id="my-hook-{env}",
        name="My Hook ({env})",
        description="A hook for {env}",
        template_file="hook-templates/my-hook-{env}.yml",
        scopes=["queue:create-task:{priority}:my-pool", "secrets:get:runtime-{env}"],
        variants=[{"group": "foo", "env": "production", "priority": "highest"}],
    )
    (result,) = generate_hook_variants([hook])
    assert result.hook_group_id == "project-foo"
    assert result.hook_id == "my-hook-production"
    assert result.name == "My Hook (production)"
    assert result.description == "A hook for production"
    assert result.template_file == "hook-templates/my-hook-production.yml"
    assert result.scopes == [
        "queue:create-task:highest:my-pool",
        "secrets:get:runtime-production",
    ]


def test_multiple_variants():
    hook = make_hook(
        hook_id="my-hook-{env}",
        variants=[{"env": "production"}, {"env": "testing"}],
    )
    result = list(generate_hook_variants([hook]))
    assert [r.hook_id for r in result] == ["my-hook-production", "my-hook-testing"]


@pytest.mark.parametrize(
    "field,value,env,expected",
    [
        (
            "template_file",
            {"by-env": {"production": "tmpl-prod.yml", "testing": "tmpl-test.yml"}},
            "production",
            "tmpl-prod.yml",
        ),
    ],
)
def test_by_key_in_field(field, value, env, expected):
    hook = make_hook(**{field: value}, variants=[{"env": env}])
    (result,) = generate_hook_variants([hook])
    assert getattr(result, field) == expected


@pytest.mark.parametrize(
    "hook_id_tpl,base_attrs,variant,expected_id",
    [
        (
            "my-hook-{env}-{level}",
            {"level": "3"},
            {"env": "production"},
            "my-hook-production-3",
        ),
        ("my-hook-{level}", {"level": "1"}, {"level": "3"}, "my-hook-3"),
    ],
)
def test_attributes(hook_id_tpl, base_attrs, variant, expected_id):
    hook = make_hook(hook_id=hook_id_tpl, attributes=base_attrs, variants=[variant])
    (result,) = generate_hook_variants([hook])
    assert result.hook_id == expected_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template_content,expected_task",
    [
        # Known variable is substituted
        (
            "provisionerId: {env}-provisioner\n",
            {"provisionerId": "production-provisioner"},
        ),
        # JSON-e string interpolation ${...} is left unchanged
        (
            "provisionerId: ${env}-provisioner\n",
            {"provisionerId": "${env}-provisioner"},
        ),
        # {{ is an escape for a literal {
        (
            "note: '{{ not-a-var'\n",
            {"note": "{ not-a-var"},
        ),
    ],
)
async def test_template_rendering(
    mock_ciconfig_file, set_environment, tmp_path, template_content, expected_task
):
    template = tmp_path / "my-hook.yml"
    template.write_text(template_content)

    mock_ciconfig_file(
        "hooks.yml",
        {
            "project-foo/my-hook": {
                "name": "My Hook",
                "description": "A hook",
                "owner": "test@example.com",
                "email_on_error": False,
                "scopes": [],
                "template_file": str(template),
                "variants": [{"env": "production"}],
            }
        },
    )
    with set_environment("production"):
        resources = Resources([], ["Hook=.*", "Role=hook-id:.*"])
        await update_resources(resources)
    (hook,) = [r for r in resources if hasattr(r, "task")]
    assert hook.task == expected_task


@pytest.mark.asyncio
async def test_template_unknown_variable_raises(
    mock_ciconfig_file, set_environment, tmp_path
):
    template = tmp_path / "my-hook.yml"
    template.write_text("provisionerId: {typo}-provisioner\n")

    mock_ciconfig_file(
        "hooks.yml",
        {
            "project-foo/my-hook": {
                "name": "My Hook",
                "description": "A hook",
                "owner": "test@example.com",
                "email_on_error": False,
                "scopes": [],
                "template_file": str(template),
                "variants": [{"env": "production"}],
            }
        },
    )
    with set_environment("production"), pytest.raises(KeyError, match="typo"):
        resources = Resources([], ["Hook=.*", "Role=hook-id:.*"])
        await update_resources(resources)


@pytest.mark.asyncio
async def test_fetch_all_with_variants(mock_ciconfig_file):
    mock_ciconfig_file(
        "hooks.yml",
        {
            "project-foo/my-hook-{env}": {
                "name": "My Hook ({env})",
                "description": "A hook for {env}",
                "owner": "test@example.com",
                "email_on_error": False,
                "scopes": ["queue:create-task:lowest:my-pool"],
                "template_file": "hook-templates/project-foo/my-hook-{env}.yml",
                "variants": [{"env": "production"}, {"env": "testing"}],
            }
        },
    )
    hooks = await Hook.fetch_all()
    result = list(generate_hook_variants(hooks))
    assert len(result) == 2
    assert result[0].hook_group_id == "project-foo"
    assert result[0].hook_id == "my-hook-production"
    assert result[1].hook_id == "my-hook-testing"
