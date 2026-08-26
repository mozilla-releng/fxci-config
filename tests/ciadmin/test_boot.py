# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json

import pytest
from tcadmin import generate
from tcadmin.appconfig import AppConfig
from tcadmin.options import test_options as click_test_options
from tcadmin.resources import Client, Resources, Role
from tcadmin.util.matchlist import MatchList

import ciadmin.boot  # noqa: F401 -- import for its generate.resources patch


def make_generated_file(tmp_path):
    resources = Resources(managed=MatchList(["Role=.*", "Client=.*"]))
    with AppConfig._as_current(AppConfig()):
        resources.add(Role(roleId="test-role", scopes=[], description="test"))
        resources.add(Client(clientId="test-client", scopes=[], description="test"))

    path = tmp_path / "generated.json"
    path.write_text(json.dumps(resources.to_json()))
    return str(path)


@pytest.mark.asyncio
async def test_generated_with_only_filters_by_module(tmp_path):
    path = make_generated_file(tmp_path)

    with AppConfig._as_current(ciadmin.boot.appconfig):
        with click_test_options(generated=path, only="grants"):
            resources = await generate.resources()

    assert {r.id for r in resources} == {"Role=test-role"}
    # `current.resources(expected.managed)` is what `diff`/`apply` actually
    # scope their live Taskcluster query to, so this must be restricted too
    # -- otherwise filtering the resource list doesn't avoid needing scopes
    # (e.g. auth:list-clients) for the excluded modules.
    assert not resources.managed.matches("Client=test-client")


@pytest.mark.asyncio
async def test_generated_without_only_returns_everything(tmp_path):
    path = make_generated_file(tmp_path)

    with AppConfig._as_current(ciadmin.boot.appconfig):
        with click_test_options(generated=path, only=None):
            resources = await generate.resources()

    assert {r.id for r in resources} == {"Role=test-role", "Client=test-client"}
