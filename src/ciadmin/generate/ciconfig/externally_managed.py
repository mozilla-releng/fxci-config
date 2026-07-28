# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re
from itertools import chain

from .get import get_ciconfig_file

# functools.cache doesn't apply to coroutines (it would cache the awaitable,
# which can only be awaited once), so use the same module-level dict pattern
# used by ciconfig/get.py for caching async lookups.
_cache = {}


async def get_externally_managed_patterns():
    """
    Load externally-managed.yml and return a flat list of all regex pattern
    strings across all projects.
    """
    if "patterns" not in _cache:
        data = await get_ciconfig_file("externally-managed.yml")
        _cache["patterns"] = list(chain.from_iterable(data.values()))
    return _cache["patterns"]


async def manage_with_exclusions(resources, base_pattern):
    """
    Call resources.manage() with a pattern that matches base_pattern but
    excludes any externally-managed resources (as defined in
    externally-managed.yml).

    For example:
        await manage_with_exclusions(resources, "WorkerPool=.*")

    Would manage all worker pools EXCEPT those listed in externally-managed.yml.

    Uses a negative lookahead so that tc-admin won't manage (and therefore
    won't delete) externally-managed resources. Note: tc-admin's
    Resources.filter() is not suitable here — it filters the generated
    resources list, not the managed patterns.
    """
    exclusion_patterns = await get_externally_managed_patterns()

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
