# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from tcadmin.resources import Client

from .ciconfig.clients import Client as ClientConfig
from .ciconfig.clients_interpreted import Client as InterpretedClientConfig
from .ciconfig.environment import Environment


async def update_resources(resources):
    """
    Manage the hooks and roles for cron tasks
    """
    clients = await ClientConfig.fetch_all()
    interpreted_clients = await InterpretedClientConfig.fetch_all()
    environment = await Environment.current()

    resources.manage("Client=(?!mozilla-auth0/|static/taskcluster/)")

    for client in clients:
        if client.environments and environment.name not in client.environments:
            # skip grant for this environment
            continue
        resources.add(
            Client(
                clientId=client.client_id,
                description=client.description,
                scopes=client.scopes,
            )
        )

    # Interpreted clients are now pre-expanded in clients.yml,
    # so this loop processes an empty list.
    for client in interpreted_clients:
        if client.environments and environment.name not in client.environments:
            continue
        resources.add(
            Client(
                clientId=client.client_id,
                description=client.description,
                scopes=client.scopes,
            )
        )
