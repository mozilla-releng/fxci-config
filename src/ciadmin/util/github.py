# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import sys

from simple_github import AsyncClient, client_from_env

# Global shared client session
_client: AsyncClient | None = None
_client_lock = asyncio.Lock()


async def get_client():
    """Get a shared GitHub client that can be reused across all GitHub API calls.

    This helps avoid resource exhaustion by avoiding creation of hundreds of
    individual client sessions, each with their own connection pools and DNS
    resolvers.
    """
    global _client, _client_lock

    async with _client_lock:
        if _client is None:
            client_cls = client_from_env("mozilla-releng", ["fxci-config"])
            _client = client_cls()  # type: ignore

    return _client


async def close_client():
    """Cleanup the shared global client."""
    global _client, _client_lock

    async with _client_lock:
        if _client is not None:
            await _client.close()
            _client = None


async def graphql(query, **variables):
    """Run `query` against GitHub's GraphQL API.

    Returns `(data, errors)`, both for the caller to interpret. GitHub answers
    a partially resolvable query with both: asking for a file across many
    branches yields the branches that have it in `data`, plus one `NOT_FOUND`
    error per branch that doesn't. Only the caller knows which of those errors
    it can ignore, so this raises for nothing that GitHub itself answered.

    `data` is None when the query didn't run at all -- a bad field, a
    repository the token can't see. GitHub reports that as HTTP 200 with the
    failure only in the body, and always alongside an error explaining it.
    """
    client = await get_client()
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
