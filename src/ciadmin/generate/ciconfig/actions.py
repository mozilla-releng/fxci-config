# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import itertools

import attr

from .get import get_ciconfig_file

DEFAULT_INPUT_SCHEMA = {
    "anyOf": [
        {"type": "object", "description": "user input for the task"},
        {"const": None, "description": "null when the action takes no input"},
    ]
}


@attr.s(frozen=True)
class Action:
    trust_domain: str = attr.ib(type=str)
    level: int = attr.ib(type=int)
    action_perm: str = attr.ib(type=str)
    input_schema: dict = attr.ib(default=DEFAULT_INPUT_SCHEMA)

    @staticmethod
    async def fetch_all():
        """Load project metadata from actions.yml in ci-configuration"""

        def build_actions(trust_domain, levels, action_perms, **kwargs):
            """
            Expand ``levels`` and action_perms`` into an entry for each combination.
            """
            return [
                Action(
                    trust_domain=trust_domain,
                    level=level,
                    action_perm=action_perm,
                    **kwargs,
                )
                for (level, action_perm) in itertools.product(levels, action_perms)
            ]

        actions = await get_ciconfig_file("actions.yml")
        return [action for info in actions for action in build_actions(**info)]
