# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import attr

from ...util.matching import ProjectGrantee


@attr.s(frozen=True)
class Client:
    client_id = attr.ib(type=str)
    scopes = attr.ib(type=list)
    description = attr.ib(type=str)
    grantee = attr.ib(type=ProjectGrantee, default=None)
    environments = attr.ib(type=list, default=None)

    @staticmethod
    async def fetch_all():
        """Interpreted clients are now pre-expanded in clients.yml.

        This returns an empty list; the entry point is preserved so that
        existing callers (clients.py update_resources) continue to work.
        """
        return []
