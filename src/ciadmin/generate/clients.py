# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from tcadmin.resources import Client

from .ciconfig.clients import Client as ClientConfig
from .ciconfig.clients_interpreted import Client as InterpretedClientConfig
from .ciconfig.environment import Environment
from .ciconfig.projects import Project
from .grants import project_match


async def update_resources(resources):
    """
    Manage the hooks and roles for cron tasks
    """
    clients = await ClientConfig.fetch_all()
    interpreted_clients = await InterpretedClientConfig.fetch_all()
    projects = await Project.fetch_all()
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

    for client in interpreted_clients:
        if client.environments and environment.name not in client.environments:
            # skip grant for this environment
            continue

        clients = []

        for project in projects:
            if project_match(client.grantee, project):
                subs = {"trust_domain": project.trust_domain}
                resources.add(
                    Client(
                        clientId=client.client_id.format(**subs),
                        description=client.description.format(**subs),
                        scopes=[s.format(**subs) for s in client.scopes],
                    )
                )
