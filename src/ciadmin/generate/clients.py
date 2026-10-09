# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re

from tcadmin.resources import Client
from tcadmin.util.matchlist import Match, MatchList

from .ciconfig.clients import Client as ClientConfig
from .ciconfig.clients_interpreted import Client as InterpretedClientConfig
from .ciconfig.environment import Environment
from .ciconfig.projects import Project
from .grants import project_match

managed = MatchList(
    [
        Match(
            "Client=.*",
            excludes=[
                "Client=mozilla-auth0/.*",
                "Client=static/taskcluster/.*",
            ],
        ),
    ]
)

# Matches scriptworker client ids, e.g.
# `project/releng/scriptworker/v2/beetmover/prod/firefoxci-gecko-3`.
SCRIPTWORKER_CLIENT_RE = re.compile(
    r"^project/releng/scriptworker/v2/(?P<type>[^/]+)/[^/]+/firefoxci-(?P<trust_domain>.+)-(?P<level>\d+|t)$"
)


def add_scriptworker_client_scopes(scopes, client_id, projects):
    """
    Add scopes for scriptworker clients based on project features.
    """
    match = SCRIPTWORKER_CLIENT_RE.match(client_id)
    if not match:
        return

    # `t` (test) clients are equivalent to level 1
    level = 1 if match["level"] == "t" else int(match["level"])
    feature = f"scriptworker-{match['type']}"
    for project in projects:
        if (
            not project.feature(feature)
            or project.trust_domain != match["trust_domain"]
            # This check ensures that if a project only has L1 branches, an L3
            # scriptworker client doesn't get scopes for it (not needed).
            or all(not b.level or b.level < level for b in project.branches)
        ):
            continue

        if project.repo.startswith("https://github.com/"):
            scopes.append(f"auth:github-repo-token:read/{project.repo_path}:*")


async def update_resources(resources):
    """
    Manage the hooks and roles for cron tasks
    """
    clients = await ClientConfig.fetch_all()
    interpreted_clients = await InterpretedClientConfig.fetch_all()
    projects = await Project.fetch_all()
    environment = await Environment.current()

    for client in clients:
        if client.environments and environment.name not in client.environments:
            # skip grant for this environment
            continue
        scopes = list(client.scopes)
        add_scriptworker_client_scopes(scopes, client.client_id, projects)
        resources.add(
            Client(
                clientId=client.client_id,
                description=client.description,
                scopes=scopes,
            )
        )

    for client in interpreted_clients:
        if client.environments and environment.name not in client.environments:
            # skip grant for this environment
            continue

        for project in projects:
            if project_match(client.grantee, project):
                subs = {"trust_domain": project.trust_domain}
                client_id = client.client_id.format(**subs)
                scopes = [s.format(**subs) for s in client.scopes]
                add_scriptworker_client_scopes(scopes, client_id, [project])
                resources.add(
                    Client(
                        clientId=client_id,
                        description=client.description.format(**subs),
                        scopes=scopes,
                    )
                )
