# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re

from .get import get_ciconfig_file


async def get_externally_managed_patterns():
    """
    Load externally-managed.yml and return a flat list of all regex pattern
    strings across all projects.
    """
    data = await get_ciconfig_file("externally-managed.yml")
    patterns = []
    for project_patterns in data.values():
        patterns.extend(project_patterns)
    return patterns


def manage_with_exclusions(resources, base_pattern, exclusion_patterns):
    """
    Call resources.manage() with a pattern that matches base_pattern but
    excludes any resources matching the exclusion patterns.

    For example:
        manage_with_exclusions(resources, "WorkerPool=.*",
            ["WorkerPool=proj-fuzzing/.*"])

    Would manage all worker pools EXCEPT those in proj-fuzzing/.

    Uses a negative lookahead so that tc-admin won't manage (and therefore
    won't delete) externally-managed resources. Note: tc-admin's
    Resources.filter() is not suitable here — it filters the generated
    resources list, not the managed patterns.
    """
    kind_match = re.match(r"^(\w+)=", base_pattern)
    if not kind_match:
        resources.manage(base_pattern)
        return

    kind_prefix = kind_match.group(1) + "="
    relevant = [p for p in exclusion_patterns if p.startswith(kind_prefix)]

    if not relevant:
        resources.manage(base_pattern)
        return

    # Build negative lookahead: (?!pat1|pat2)base_pattern
    resources.manage(f"(?!{'|'.join(relevant)}){base_pattern}")


def manage_individual(resources, resource_id):
    """
    Manage a single specific resource by its exact ID.
    Used for resources in externally-managed namespaces that we DO generate.
    """
    resources.manage(re.escape(resource_id) + "$")
