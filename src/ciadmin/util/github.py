# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio

import aiohttp
from simple_github import AsyncClient, client_from_env

# Global shared client session
_client: AsyncClient | None = None
_client_lock = asyncio.Lock()

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1
RETRY_STATUSES = frozenset({502})


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


async def request_with_retry(
    method,
    query,
    *,
    attempts=RETRY_ATTEMPTS,
    retry_statuses=RETRY_STATUSES,
    backoff_seconds=RETRY_BACKOFF_SECONDS,
    **kwargs,
):
    """Make a GitHub API request and retry transient HTTP responses."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    client = await get_client()

    for attempt in range(1, attempts + 1):
        response = await client.request(method, query, **kwargs)
        try:
            response.raise_for_status()
            return response
        except aiohttp.ClientResponseError as e:
            if e.status not in retry_statuses or attempt == attempts:
                raise

            response.release()
            print(
                f"Got error when querying {query}: {e}. "
                f"Retrying ({attempt + 1}/{attempts})..."
            )
            await asyncio.sleep(backoff_seconds * 2 ** (attempt - 1))


async def close_client():
    """Cleanup the shared global client."""
    global _client, _client_lock

    async with _client_lock:
        if _client is not None:
            await _client.close()
            _client = None
