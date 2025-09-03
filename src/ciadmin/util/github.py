# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio

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
