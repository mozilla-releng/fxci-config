# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json

from tcadmin.resources import Resources
from tcadmin.util.matchlist import MatchList


def load_generated(path):
    """Load a `Resources` set previously written by `tc-admin generate --json`."""
    with open(path) as f:
        return Resources.from_json(json.load(f))


def filter_generated(resources, modules, resource_modules):
    """Return the subset of RESOURCES belonging to the named MODULES.

    Membership is determined by matching each resource's id against the
    requested modules' `managed` MatchLists, since a loaded `Resources` set
    has no per-resource record of which generator produced it.
    """
    if not modules:
        return resources

    managed = MatchList([])
    for name in modules:
        managed.extend(resource_modules[name].managed)

    filtered = Resources(managed=managed)
    for r in resources:
        if managed.matches(r.id):
            filtered.add(r)
    return filtered
