# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json

from tcadmin.appconfig import AppConfig
from tcadmin.resources import Client, Resources, Role
from tcadmin.util.matchlist import MatchList

from ciadmin.util.generated import filter_generated, load_generated


def make_resources():
    resources = Resources(managed=MatchList(["Role=.*", "Client=.*"]))
    with AppConfig._as_current(AppConfig()):
        resources.add(Role(roleId="test-role", scopes=[], description="test"))
        resources.add(Client(clientId="test-client", scopes=[], description="test"))
    return resources


def test_load_generated(tmp_path):
    resources = make_resources()
    path = tmp_path / "generated.json"
    path.write_text(json.dumps(resources.to_json()))

    with AppConfig._as_current(AppConfig()):
        loaded = load_generated(str(path))

    assert {r.id for r in loaded} == {r.id for r in resources}


def test_filter_generated_without_modules_returns_everything():
    resources = make_resources()

    assert filter_generated(resources, [], {}) is resources


def test_filter_generated_restricts_to_named_modules():
    resources = make_resources()
    resource_modules = {
        "grants": type("grants", (), {"managed": MatchList(["Role=.*"])}),
        "clients": type("clients", (), {"managed": MatchList(["Client=.*"])}),
    }

    filtered = filter_generated(resources, ["grants"], resource_modules)

    assert {r.id for r in filtered} == {"Role=test-role"}
    # managed is restricted to the requested modules too, not the source's
    # full managed list -- callers scope `current.resources()` off of this.
    assert filtered.managed.matches("Role=test-role")
    assert not filtered.managed.matches("Client=test-client")
