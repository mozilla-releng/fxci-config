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
    """
    # Filter exclusion patterns to only those relevant to the base pattern kind
    # (e.g., if base is "WorkerPool=.*", only include "WorkerPool=..." exclusions)
    kind_match = re.match(r"^(\w+)=", base_pattern)
    kind_prefix = kind_match.group(1) + "=" if kind_match else ""

    relevant_exclusions = []
    for pat in exclusion_patterns:
        if pat.startswith(kind_prefix):
            # Strip the Kind= prefix for the negative lookahead
            relevant_exclusions.append(pat)

    if not relevant_exclusions:
        resources.manage(base_pattern)
        return

    # Build a negative lookahead pattern
    exclusion_alts = "|".join(relevant_exclusions)
    pattern = f"(?!{exclusion_alts}){base_pattern}"
    resources.manage(pattern)


def manage_individual(resources, resource_id):
    """
    Manage a single specific resource by its exact ID.
    Used for resources in externally-managed namespaces that we DO generate.
    """
    resources.manage(re.escape(resource_id) + "$")
