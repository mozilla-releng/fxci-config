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
# token is minted for a single repository.
_fallback_client: AsyncClient | None = None
_fallback_lock = asyncio.Lock()

_warned = set()


class RepoTokenAuth(Auth):
    """Credentials for one repository, minted by Taskcluster's auth service.

    The token covers `repo_path` alone, and github expires it after an hour
    with no way to extend it. `simple_github` asks for the token on every
    request and rebuilds its session whenever the value changes, so replacing
    an expired one here needs nothing from the caller.
    """

    def __init__(self, repo_path):
        self._owner, self._name = repo_path.split("/")
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
                    {"repositories": [self._name], "permissions": PERMISSIONS},
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


def can_read_private_repos():
    """Whether this run can ask the auth service for a repository token.

    Without Taskcluster credentials there is no token, and github answers for
    a private repository as though it did not exist. A pull request from a
    fork is the usual case, since github withholds every secret from those.
    """
    return "credentials" in optionsFromEnvironment()


async def _build_client(repo_path):
    if not can_read_private_repos():
        _warn_once(
            "No Taskcluster credentials in the environment; private "
            "repositories will not be readable."
        )
        return await _get_fallback_client()

    auth = RepoTokenAuth(repo_path)
    try:
        # Fetched here rather than on first use, so that a refusal picks the
        # fallback instead of failing whichever request happens to be first.
        await auth.get_token()
    except TaskclusterFailure as e:
        _warn_once(
            f"Could not get a github token for {repo_path} from the auth "
            f"service, falling back to the environment: {e}"
        )
        return await _get_fallback_client()

    return AsyncClient(auth=auth)


async def get_client(repo_path):
    """Get a GitHub client that can reach the repository at `repo_path`.

    `repo_path` is `owner/name`. Each repository gets its own client, because
    the token behind it is minted for that repository alone.
    """
    async with _client_locks.setdefault(repo_path, asyncio.Lock()):
        if repo_path not in _clients:
            _clients[repo_path] = await _build_client(repo_path)

    return _clients[repo_path]


async def close_clients():
    """Cleanup every client this module has handed out."""
    global _fallback_client

    for repo_path in list(_clients):
        async with _client_locks[repo_path]:
            client = _clients.pop(repo_path)
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
