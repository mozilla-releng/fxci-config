# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
from asyncio import Lock

import aiohttp
from aiohttp_retry import ExponentialRetry, RetryClient
from tcadmin.util.sessions import aiohttp_session

_cache = {}
_lock = {}


# TODO: support private repositories. this will most likely require querying
# GitHub as an app.
async def get(repo_path, repo_type="git"):
    """Get the list of branches present in `repo_path`. Only supported for
    public GitHub repositories."""
    if repo_type != "git":
        raise Exception("Branches can only be fetched for git repositories!")

    if repo_path.endswith("/"):
        repo_path = repo_path[:-1]
    branches_url = f"https://api.github.com/repos/{repo_path}/branches"

    # 100 is the maximum allowed
    # https://docs.github.com/en/rest/branches/branches?apiVersion=2022-11-28#list-branches
    params = {"per_page": 100}
    headers = {}
    if "GITHUB_TOKEN" in os.environ:
        github_token = os.environ["GITHUB_TOKEN"]
        headers["Authorization"] = f"Bearer {github_token}"

    async with _lock.setdefault(repo_path, Lock()):
        if repo_path in _cache:
            return _cache[repo_path]

        branches = []
        client = RetryClient(
            client_session=aiohttp_session(),
            retry_options=ExponentialRetry(attempts=5),
        )
        while branches_url:
            async with client.get(
                branches_url, headers=headers, params=params
            ) as response:
                try:
                    response.raise_for_status()
                    result = await response.json()
                    branches.extend([b["name"] for b in result])
                    # If `link` is present in the response it will contain
                    # pagination information. We need to examine it to see
                    # if there are additional pages of results to fetch.
                    # See https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api?apiVersion=2022-11-28#using-link-headers
                    # for a full description of the responses.
                    # This icky parsing can probably go away when we switch
                    # to a GitHub app, as we'll likely be using a proper
                    # client at that point.
                    for l in response.headers.get("link", "").split(","):
                        if 'rel="next"' in l:
                            branches_url = l.split(">")[0].split("<")[1]
                            break
                    else:
                        branches_url = None
                except aiohttp.ClientResponseError as e:
                    print(f"Got error when querying {branches_url}: {e}")
                    raise e

        _cache[repo_path] = branches
        return _cache[repo_path]
