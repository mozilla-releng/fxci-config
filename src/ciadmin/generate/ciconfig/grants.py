# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import attr

from ...util.matching import grantees
from .get import get_ciconfig_file


@attr.s(frozen=True)
class Grant:
    scopes: list = attr.ib(type=list, factory=lambda: [])
    grantees: list = attr.ib(type=list, factory=lambda: [])
    environments: list = attr.ib(type=list, default=None)

    @scopes.validator
    def validate_scopes(self, attribute, value):
        if not isinstance(value, list):
            raise ValueError("scopes must be a list")
        if any(not isinstance(s, str) for s in value):
            raise ValueError("scopes must be a list of strings")

    @staticmethod
    async def fetch_all():
        """Load project metadata from grants.yml in ci-configuration"""
        grants = await get_ciconfig_file("grants.yml")

        return [
            Grant(
                scopes=grant["grant"],
                grantees=grantees(grant["to"]),
                environments=grant.get("environments"),
            )
            for grant in grants
        ]
