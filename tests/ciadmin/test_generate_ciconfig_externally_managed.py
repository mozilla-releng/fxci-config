# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from tcadmin.resources import Resources

from ciadmin.generate.ciconfig.externally_managed import manage_individual


def test_manage_individual_exact_match():
    "manage_individual matches only the exact id, not siblings in the group."
    resources = Resources([], [])
    manage_individual(resources, "Hook=project-fuzzing/bugmon")

    assert resources.is_managed("Hook=project-fuzzing/bugmon")
    assert not resources.is_managed("Hook=project-fuzzing/bugmon-confirm")
    assert not resources.is_managed("Hook=project-fuzzing/other")


def test_manage_individual_prefix_is_literal():
    """
    The managed pattern must start with the literal `Kind=<group>/` prefix even
    when the group name contains `-`.

    tcadmin's `current.hooks.fetch_hooks` decides whether to query a hook group
    with `pattern.startswith("Hook=<group>/")`. If `re.escape` rewrites the `-`
    in a group name as `\\-`, that check fails, the group is skipped, and hooks
    we generate there show up as phantom additions.
    """
    resources = Resources([], [])
    manage_individual(resources, "Hook=project-fuzzing/bugmon")

    (pattern,) = list(resources.managed)
    assert pattern.startswith("Hook=project-fuzzing/")
