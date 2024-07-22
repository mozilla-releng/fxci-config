# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import attr

from .get import get_ciconfig_file


@attr.s(frozen=True)
class Client:
    client_id: str = attr.ib(type=str)
    scopes: list = attr.ib(type=list)
    description: str = attr.ib(type=str)
    environments: list = attr.ib(type=list, default=None)

    @staticmethod
    async def fetch_all():
        """Load hook metadata from hooks.yml in ci-configuration"""
        clients = await get_ciconfig_file("clients.yml")

        return [Client(client_id, **info) for client_id, info in clients.items()]
