# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import sys
from datetime import UTC, datetime, timedelta

import taskcluster.aio
from simple_github import AsyncClient, client_from_env
from simple_github.auth import Auth
from taskcluster import optionsFromEnvironment
from taskcluster.exceptions import TaskclusterFailure
from tcadmin.util.sessions import aiohttp_session

from ciadmin.generate.ciconfig.projects import Project

# The read-only GitHub app the auth service mints tokens for. It is installed
# on the repositories fxci-config manages, which is what makes the private
# ones readable at all.
GITHUB_APP = "read"

# Branch names and `.taskcluster.yml` are both repository contents.
PERMISSIONS = {"contents": "read"}

# Replace a token this long before github's stated expiry, so that no request
# is signed with one that dies on the way.
REFRESH_MARGIN = timedelta(minutes=5)

_clients = {}
_client_locks = {}

# Every fallback client would be built from the same environment, so one
# answers for all of them. A token client cannot be shared that way, since its
# token names the repositories of a single owner.
_fallback_client: AsyncClient | None = None
_fallback_lock = asyncio.Lock()

_warned = set()


class OwnerTokenAuth(Auth):
    """Credentials for one owner's repositories, from Taskcluster's auth service.

    A single token covers every repository named in `repositories`, so an owner
    costs one call rather than one per repository. Github expires it after an
    hour with no way to extend it. `simple_github` asks for the token on every
    request and rebuilds its session whenever the value changes, so replacing
    an expired one here needs nothing from the caller.
    """

    def __init__(self, owner, repositories):
        self._owner = owner
        self._repositories = repositories
        self._token = None
        self._expires = datetime.min.replace(tzinfo=UTC)
        self._lock = asyncio.Lock()

    async def get_token(self):
        async with self._lock:
            if datetime.now(UTC) + REFRESH_MARGIN >= self._expires:
                auth = taskcluster.aio.Auth(
                    optionsFromEnvironment(), session=aiohttp_session()
                )
                response = await auth.githubRepoToken(
                    GITHUB_APP,
                    self._owner,
                    {
                        "repositories": self._repositories,
                        "permissions": PERMISSIONS,
                    },
                )
                self._token = response["token"]
                self._expires = datetime.fromisoformat(response["expires"])

        return self._token


def _warn_once(message):
    """Print `message` to stderr, but only the first time it is seen.

    A failure to mint a token repeats for every repository, and the same
    sentence forty times hides everything around it.
    """
    if message not in _warned:
        _warned.add(message)
        print(message, file=sys.stderr)


async def _get_fallback_client():
    """The shared client built from `GITHUB_TOKEN` or the app in the environment.

    It cannot read a private repository. It is what keeps runs without
    Taskcluster credentials, such as a pull request from a fork, working for
    the public ones.
    """
    global _fallback_client

    async with _fallback_lock:
        if _fallback_client is None:
            client_cls = client_from_env("mozilla-releng", ["fxci-config"])
            _fallback_client = client_cls()  # type: ignore

    return _fallback_client


async def _owner_repositories(owner):
    """Every github repository `owner` has in projects.yml.

    A token names the repositories it covers, and a repository left out of the
    list is one the token cannot read. Globbed entries name no repository, so
    they are dropped.
    """
    projects = await Project.fetch_all()
    return sorted(
        {
            project.repo_path.split("/", 1)[1].lower()
            for project in projects
            if project.repo_type == "git"
            and "*" not in project.repo
            and project.repo_path.split("/", 1)[0].lower() == owner
        }
    )


async def _build_client(owner):
    auth = OwnerTokenAuth(owner, await _owner_repositories(owner))
    try:
        # Fetched here rather than on first use, so that a refusal picks the
        # fallback instead of failing whichever request happens to be first.
        await auth.get_token()
    except TaskclusterFailure as e:
        _warn_once(
            f"Could not get a github token for {owner} from the auth service, "
            f"falling back to the environment: {e}"
        )
        return await _get_fallback_client()

    return AsyncClient(auth=auth)


async def get_client(repo_path):
    """Get a GitHub client that can reach the repository at `repo_path`.

    `repo_path` is `owner/name`. One client serves each owner, since a single
    token covers every repository that owner has in projects.yml.
    """
    owner = repo_path.split("/", 1)[0].lower()

    async with _client_locks.setdefault(owner, asyncio.Lock()):
        if owner not in _clients:
            _clients[owner] = await _build_client(owner)

    return _clients[owner]


async def close_clients():
    """Cleanup every client this module has handed out."""
    global _fallback_client

    for owner in list(_clients):
        async with _client_locks[owner]:
            client = _clients.pop(owner)
            if client is not _fallback_client:
                await client.close()

    async with _fallback_lock:
        if _fallback_client is not None:
            await _fallback_client.close()
            _fallback_client = None


async def graphql(repo_path, query, **variables):
    """Run `query` against GitHub's GraphQL API for the repository `repo_path`.

    Returns `(data, errors)`, both for the caller to interpret. GitHub answers
    a partially resolvable query with both: asking for a file across many
    branches yields the branches that have it in `data`, plus one `NOT_FOUND`
    error per branch that doesn't. Only the caller knows which of those errors
    it can ignore, so this raises for nothing that GitHub itself answered.

    `data` is None when the query didn't run at all -- a bad field, a
    repository the token can't see. GitHub reports that as HTTP 200 with the
    failure only in the body, and always alongside an error explaining it.
    """
    client = await get_client(repo_path)
    response = await client.request(
        "POST", "/graphql", json={"query": query, "variables": variables}
    )
    if not response.ok:
        detail = await response.text()
        print(
            f"Got error when querying the GraphQL API: "
            f"{response.status} {response.reason}: {detail}",
            file=sys.stderr,
        )
        response.raise_for_status()

    body = await response.json()
    return body.get("data"), body.get("errors") or []
